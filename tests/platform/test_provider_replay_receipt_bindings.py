"""Defensive replay receipt binding regressions."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from cre_mcp.access.profiles import Profile
from cre_mcp.config import ProviderPlanMapping
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.providers.core import (
    NormalizedProviderEvent,
    ProviderSyncService,
)
from cre_mcp.platform.providers.reconciliation import ProviderReconciliationStore

from .admin_helpers import VALID_REASON, audit_rows, provision_identity
from .provider_helpers import NOW, provider_attempts, provider_config
from .test_provider_security_repairs import (
    _insert_mapping,
    _issue_tokens,
    _workspace_with_users,
)


RECEIPT_BINDING_COLUMNS = (
    "workspace_id",
    "provider",
    "event_id",
    "event_type",
    "occurred_at",
    "canonical_action",
    "external_account_hash",
    "object_stream_hash",
    "restrictive_rank",
    "bound_subject_user_id",
    "bound_scope",
)
PROJECTION_TABLES = (
    "platform_subscriptions",
    "platform_access_grants",
    "platform_accounts",
    "platform_external_accounts",
    "platform_oauth_sessions",
    "platform_oauth_codes",
)


def _provider_hash(provider: str, external_id: str) -> str:
    return hashlib.sha256(f"{provider}\0{external_id}".encode()).hexdigest()


def _receipt_bindings(path, provider_event_id: int) -> dict[str, Any]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        available = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(platform_provider_events)"
            )
        }
        selected = [
            column for column in RECEIPT_BINDING_COLUMNS if column in available
        ]
        row = connection.execute(
            f"""
            SELECT {",".join(selected)}
            FROM platform_provider_events
            WHERE id=?
            """,
            (provider_event_id,),
        ).fetchone()
    assert row is not None
    return {column: row[column] for column in selected}


def _projection_snapshot(path) -> dict[str, tuple[tuple[Any, ...], ...]]:
    with sqlite3.connect(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        return {
            table: tuple(
                tuple(row)
                for row in connection.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ).fetchall()
            )
            for table in PROJECTION_TABLES
            if table in tables
        }


def _mutate_normalized_data(
    path,
    provider_event_id: int,
    **updates: Any,
) -> dict[str, Any]:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT normalized_data FROM platform_provider_events
            WHERE id=?
            """,
            (provider_event_id,),
        ).fetchone()
        assert row is not None
        normalized = json.loads(str(row[0]))
        assert isinstance(normalized, dict)
        normalized.update(updates)
        connection.execute(
            """
            UPDATE platform_provider_events SET normalized_data=?
            WHERE id=?
            """,
            (
                json.dumps(
                    normalized,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                provider_event_id,
            ),
        )
    return normalized


def _stripe_config_with_mapping(
    config,
    selector: str,
    *,
    plan_key: str,
    profile: Profile,
):
    mappings = dict(config.stripe_price_mappings)
    mappings[selector] = ProviderPlanMapping(
        plan_key=plan_key,
        profile=profile,
    )
    return config.model_copy(update={"stripe_price_mappings": mappings})


def _stripe_subscription_event(
    *,
    event_id: str,
    account_id: str,
    object_id: str,
    selector: str,
    occurred_at: datetime = NOW,
    current_period_end: datetime | None = None,
) -> NormalizedProviderEvent:
    return NormalizedProviderEvent(
        provider="stripe",
        event_id=event_id,
        event_type="customer.subscription.updated",
        occurred_at=occurred_at,
        action="subscription",
        external_account_id=account_id,
        external_object_id=object_id,
        subscription_status="active",
        mapping_keys=(selector,),
        current_period_end=current_period_end
        or occurred_at + timedelta(days=30),
    )


def _authority_projection(path, object_id: str) -> tuple[Any, Any]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        subscription = connection.execute(
            """
            SELECT status,plan_key,current_period_end
            FROM platform_subscriptions
            WHERE provider='stripe' AND external_subscription_id=?
            """,
            (object_id,),
        ).fetchone()
        grant = connection.execute(
            """
            SELECT profile,plan_key,status,ends_at
            FROM platform_access_grants
            WHERE source='stripe' AND external_ref=?
            """,
            (object_id,),
        ).fetchone()
    return (
        tuple(subscription) if subscription is not None else None,
        tuple(grant) if grant is not None else None,
    )


def _replay(config, admin_user_id: int, provider_event_id: int):
    return ProviderReconciliationStore(
        config.cache_db_path,
        ProviderSyncService(config),
    ).replay(
        actor_user_id=admin_user_id,
        provider_event_id=provider_event_id,
        reason_code=VALID_REASON["reason_code"],
        reason=VALID_REASON["reason"],
    )


def _private_values_absent(
    config,
    caplog,
    private_values: tuple[str, ...],
) -> None:
    audits = audit_rows(config.cache_db_path)
    assert audits[-1]["action"] == "provider_event.replay"
    audited_after = json.loads(str(audits[-1]["after_json"]))
    assert audited_after["outcome"] == "quarantined"
    assert audited_after["reason_code"] in {
        "receipt_binding_mismatch",
        "legacy_receipt_binding_untrusted",
    }
    audit_text = (
        str(audits[-1]["before_json"]) + str(audits[-1]["after_json"])
    )
    for private_value in private_values:
        assert private_value not in caplog.text
        assert private_value not in audit_text


async def _failed_legacy_cancel(
    tmp_path,
    *,
    name: str,
    account_id: str,
    object_id: str,
    user_count: int = 1,
    active_at: int = 100,
    cancel_at: int = 200,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        name,
        user_count=user_count,
    )
    admin = await provision_identity(
        config,
        f"{name} Admin",
        internal_role="platform_admin",
    )
    store = EntitlementStore(config.cache_db_path)
    period_end = datetime.now(UTC) + timedelta(days=30)
    active = store.apply_subscription_event(
        provider="stripe",
        event_id=f"evt_{name.casefold().replace(' ', '_')}_active",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id=object_id,
        external_customer_id=account_id,
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=period_end,
        occurred_at=datetime.fromtimestamp(active_at, UTC),
        subject_user_id=users[0].id,
    )
    assert active.grant is not None
    auth, _, tokens = _issue_tokens(config, workspace, users)
    trigger_name = f"reject_{workspace.id}_receipt_cancel"
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OF status ON platform_subscriptions
            WHEN OLD.external_subscription_id='{object_id}'
             AND NEW.status='canceled'
            BEGIN
                SELECT RAISE(ABORT, 'injected receipt projection failure');
            END
            """
        )
    canceled = store.apply_subscription_event(
        provider="stripe",
        event_id=f"evt_{name.casefold().replace(' ', '_')}_cancel",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id=object_id,
        external_customer_id=account_id,
        subscription_status="canceled",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        occurred_at=datetime.fromtimestamp(cancel_at, UTC),
        subject_user_id=users[0].id,
    )
    assert canceled.outcome == "quarantined"
    event = next(
        item
        for item in store.list_events(workspace.id)
        if item.event_id == f"evt_{name.casefold().replace(' ', '_')}_cancel"
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(f"DROP TRIGGER {trigger_name}")
    return config, workspace, users, admin, store, active, auth, tokens, event


async def test_replay_rejects_poisoned_unmapped_selector_to_operator(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Poisoned Unmapped Selector",
    )
    admin = await provision_identity(
        config,
        "Poisoned Unmapped Selector Admin",
        internal_role="platform_admin",
    )
    account_id = "cus_poisoned_unmapped_private"
    object_id = "sub_poisoned_unmapped_private"
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    receipt = ProviderSyncService(config).ingest(
        _stripe_subscription_event(
            event_id="evt_poisoned_unmapped",
            account_id=account_id,
            object_id=object_id,
            selector="price_unmapped",
        )
    )
    assert (receipt.outcome, receipt.reason_code) == (
        "quarantined",
        "unmapped_plan",
    )
    _mutate_normalized_data(
        config.cache_db_path,
        receipt.event_db_id,
        mapping_keys=["price_operator"],
    )
    projection_before = _projection_snapshot(config.cache_db_path)

    replay = _replay(config, admin.user_id, receipt.event_db_id)

    assert (replay["outcome"], replay["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert _authority_projection(config.cache_db_path, object_id) == (
        None,
        None,
    )


async def test_replay_cannot_upgrade_existing_local_grant_to_operator(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Poisoned Lower Tier",
    )
    admin = await provision_identity(
        config,
        "Poisoned Lower Tier Admin",
        internal_role="platform_admin",
    )
    account_id = "cus_poisoned_lower_tier_private"
    object_id = "sub_poisoned_lower_tier_private"
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    service = ProviderSyncService(config)
    active = service.ingest(
        _stripe_subscription_event(
            event_id="evt_poisoned_lower_tier_active",
            account_id=account_id,
            object_id=object_id,
            selector="price_local",
        )
    )
    assert active.outcome == "applied"
    assert _authority_projection(config.cache_db_path, object_id)[1][:2] == (
        "local_scout",
        "local",
    )
    receipt = service.ingest(
        _stripe_subscription_event(
            event_id="evt_poisoned_lower_tier_quarantine",
            account_id=account_id,
            object_id=object_id,
            selector="price_unmapped",
            occurred_at=NOW + timedelta(minutes=1),
        )
    )
    assert (receipt.outcome, receipt.reason_code) == (
        "quarantined",
        "unmapped_plan",
    )
    _mutate_normalized_data(
        config.cache_db_path,
        receipt.event_db_id,
        mapping_keys=["price_operator"],
    )
    projection_before = _projection_snapshot(config.cache_db_path)

    replay = _replay(config, admin.user_id, receipt.event_db_id)

    assert (replay["outcome"], replay["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert _authority_projection(config.cache_db_path, object_id)[1][:2] == (
        "local_scout",
        "local",
    )


async def test_replay_rejects_poisoned_paid_through_extension_to_2036(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Poisoned Paid Through",
    )
    admin = await provision_identity(
        config,
        "Poisoned Paid Through Admin",
        internal_role="platform_admin",
    )
    account_id = "cus_poisoned_paid_through_private"
    object_id = "sub_poisoned_paid_through_private"
    receipt = ProviderSyncService(config).ingest(
        _stripe_subscription_event(
            event_id="evt_poisoned_paid_through",
            account_id=account_id,
            object_id=object_id,
            selector="price_local",
            current_period_end=NOW + timedelta(days=30),
        )
    )
    assert (receipt.outcome, receipt.reason_code) == (
        "quarantined",
        "unmapped_external_account",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    poisoned_end = datetime(2036, 1, 1, tzinfo=UTC)
    _mutate_normalized_data(
        config.cache_db_path,
        receipt.event_db_id,
        current_period_end=poisoned_end.isoformat(),
    )
    projection_before = _projection_snapshot(config.cache_db_path)

    replay = _replay(config, admin.user_id, receipt.event_db_id)

    assert (replay["outcome"], replay["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert _authority_projection(config.cache_db_path, object_id) == (
        None,
        None,
    )


async def test_replay_rejects_same_selector_trusted_config_authority_remap(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Trusted Config Remap",
    )
    admin = await provision_identity(
        config,
        "Trusted Config Remap Admin",
        internal_role="platform_admin",
    )
    account_id = "cus_trusted_config_remap_private"
    object_id = "sub_trusted_config_remap_private"
    receipt = ProviderSyncService(config).ingest(
        _stripe_subscription_event(
            event_id="evt_trusted_config_remap",
            account_id=account_id,
            object_id=object_id,
            selector="price_local",
        )
    )
    assert (receipt.outcome, receipt.reason_code) == (
        "quarantined",
        "unmapped_external_account",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    remapped = _stripe_config_with_mapping(
        config,
        "price_local",
        plan_key="operator",
        profile=Profile.FULL_OPERATOR,
    )
    projection_before = _projection_snapshot(config.cache_db_path)

    replay = _replay(remapped, admin.user_id, receipt.event_db_id)

    assert (replay["outcome"], replay["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert _authority_projection(config.cache_db_path, object_id) == (
        None,
        None,
    )


async def test_replay_legitimately_binds_new_mapping_once(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Legitimate Mapping Bind",
    )
    admin = await provision_identity(
        config,
        "Legitimate Mapping Bind Admin",
        internal_role="platform_admin",
    )
    account_id = "cus_legitimate_mapping_bind_private"
    object_id = "sub_legitimate_mapping_bind_private"
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    receipt = ProviderSyncService(config).ingest(
        _stripe_subscription_event(
            event_id="evt_legitimate_mapping_bind",
            account_id=account_id,
            object_id=object_id,
            selector="price_future_local",
        )
    )
    assert (receipt.outcome, receipt.reason_code) == (
        "quarantined",
        "unmapped_plan",
    )
    updated = _stripe_config_with_mapping(
        config,
        "price_future_local",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
    )

    replay = _replay(updated, admin.user_id, receipt.event_db_id)

    assert replay["outcome"] == "reconciled"
    assert _authority_projection(config.cache_db_path, object_id)[1][:2] == (
        "local_scout",
        "local",
    )
    canonical = json.dumps(
        {
            "action": "subscription",
            "current_period_end": (
                NOW + timedelta(days=30)
            ).isoformat(),
            "mapping_keys": ["price_future_local"],
            "provider": "stripe",
            "subscription_status": "active",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = "v1:" + hashlib.sha256(
        b"cre-provider-entitlement-input:v1\0" + canonical.encode("utf-8")
    ).hexdigest()
    with sqlite3.connect(config.cache_db_path) as connection:
        binding = connection.execute(
            """
            SELECT entitlement_input_hash,bound_plan_key,bound_profile
            FROM platform_provider_events WHERE id=?
            """,
            (receipt.event_db_id,),
        ).fetchone()
    assert tuple(binding) == (
        expected_hash,
        "local",
        "local_scout",
    )


def test_normalized_provider_event_authority_surface_is_explicit():
    assert set(NormalizedProviderEvent.__dataclass_fields__) == {
        "provider",
        "event_id",
        "event_type",
        "occurred_at",
        "action",
        "external_account_id",
        "external_object_id",
        "subscription_status",
        "mapping_keys",
        "current_period_end",
    }
    event = _stripe_subscription_event(
        event_id="evt_authority_surface",
        account_id="cus_authority_surface",
        object_id="sub_authority_surface",
        selector="price_local",
    )
    authority_hash = event.entitlement_input_hash()
    for changed in (
        replace(event, provider="skool"),
        replace(event, action="cancel"),
        replace(event, subscription_status="past_due"),
        replace(event, mapping_keys=("price_operator",)),
        replace(
            event,
            current_period_end=event.current_period_end
            + timedelta(seconds=1),
        ),
    ):
        assert changed.entitlement_input_hash() != authority_hash


async def test_compatibility_writer_uses_same_entitlement_binding_contract(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Compatibility Binding Contract",
    )
    period_end = NOW + timedelta(days=30)
    result = EntitlementStore(
        config.cache_db_path
    ).apply_subscription_event(
        provider="stripe",
        event_id="evt_compatibility_binding_contract",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_compatibility_binding_contract",
        external_customer_id="cus_compatibility_binding_contract",
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=period_end,
        occurred_at=NOW,
        subject_user_id=users[0].id,
    )
    canonical = json.dumps(
        {
            "action": "subscription",
            "current_period_end": period_end.isoformat(),
            "mapping_keys": [],
            "provider": "stripe",
            "subscription_status": "active",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    expected_hash = "v1:" + hashlib.sha256(
        b"cre-provider-entitlement-input:v1\0" + canonical.encode("utf-8")
    ).hexdigest()
    with sqlite3.connect(config.cache_db_path) as connection:
        binding = connection.execute(
            """
            SELECT entitlement_input_hash,bound_plan_key,bound_profile
            FROM platform_provider_events WHERE id=?
            """,
            (result.event.id,),
        ).fetchone()
    assert tuple(binding) == (
        expected_hash,
        "local",
        "local_scout",
    )


async def test_replay_rejects_equal_rank_exact_action_change(
    tmp_path,
    caplog,
):
    account_id = "cus_exact_action_private"
    object_id = "sub_exact_action_private"
    (
        config,
        _workspace,
        _users,
        admin,
        _store,
        _active,
        auth,
        tokens,
        event,
    ) = await _failed_legacy_cancel(
        tmp_path,
        name="Exact Action Binding",
        account_id=account_id,
        object_id=object_id,
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        row = connection.execute(
            "SELECT normalized_data FROM platform_provider_events WHERE id=?",
            (event.id,),
        ).fetchone()
        assert row is not None
        normalized = json.loads(str(row[0]))
        normalized["action"] = "pause"
        connection.execute(
            "UPDATE platform_provider_events SET normalized_data=? WHERE id=?",
            (
                json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                event.id,
            ),
        )
    bindings_before = _receipt_bindings(config.cache_db_path, event.id)
    projection_before = _projection_snapshot(config.cache_db_path)

    caplog.set_level(logging.WARNING)
    result = _replay(config, admin.user_id, event.id)

    assert result["outcome"] == "quarantined"
    assert result["reason_code"] == "receipt_binding_mismatch"
    assert _receipt_bindings(config.cache_db_path, event.id) == bindings_before
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert set(RECEIPT_BINDING_COLUMNS) == set(bindings_before)
    assert auth.validate_access(tokens[0].access_token) is not None
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event.id
    ]
    assert (attempts[-1]["outcome"], attempts[-1]["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    _private_values_absent(config, caplog, (account_id, object_id))


async def test_replay_rejects_same_workspace_account_subject_redirection(
    tmp_path,
    caplog,
):
    account_id = "cus_same_workspace_private"
    object_id = "sub_same_workspace_private"
    (
        config,
        workspace,
        users,
        admin,
        _store,
        _active,
        auth,
        tokens,
        event,
    ) = await _failed_legacy_cancel(
        tmp_path,
        name="Same Workspace Binding",
        account_id=account_id,
        object_id=object_id,
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            UPDATE platform_external_accounts
            SET subject_user_id=?,updated_at=?
            WHERE provider='stripe' AND external_account_id=?
            """,
            (users[1].id, datetime.now(UTC).isoformat(), account_id),
        )
    bindings_before = _receipt_bindings(config.cache_db_path, event.id)
    projection_before = _projection_snapshot(config.cache_db_path)

    caplog.set_level(logging.WARNING)
    result = _replay(config, admin.user_id, event.id)

    assert result["outcome"] == "quarantined"
    assert result["reason_code"] == "receipt_binding_mismatch"
    assert _receipt_bindings(config.cache_db_path, event.id) == bindings_before
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert set(RECEIPT_BINDING_COLUMNS) == set(bindings_before)
    assert auth.validate_access(tokens[0].access_token) is not None
    assert auth.validate_access(tokens[1].access_token) is not None
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event.id
    ]
    assert attempts[-1]["reason_code"] == "receipt_binding_mismatch"
    _private_values_absent(config, caplog, (account_id, object_id))


async def test_replay_after_bound_membership_removal_records_mismatch(
    tmp_path,
    caplog,
):
    account_id = "cus_removed_member_private"
    object_id = "sub_removed_member_private"
    (
        config,
        workspace,
        users,
        admin,
        _store,
        _active,
        _auth,
        _tokens,
        event,
    ) = await _failed_legacy_cancel(
        tmp_path,
        name="Removed Member Binding",
        account_id=account_id,
        object_id=object_id,
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            DELETE FROM platform_memberships
            WHERE workspace_id=? AND user_id=?
            """,
            (workspace.id, users[0].id),
        )
        connection.execute(
            """
            UPDATE platform_external_accounts
            SET subject_user_id=?,updated_at=?
            WHERE provider='stripe' AND external_account_id=?
            """,
            (users[1].id, datetime.now(UTC).isoformat(), account_id),
        )
    bindings_before = _receipt_bindings(config.cache_db_path, event.id)
    projection_before = _projection_snapshot(config.cache_db_path)

    caplog.set_level(logging.WARNING)
    result = _replay(config, admin.user_id, event.id)

    assert result["outcome"] == "quarantined"
    assert result["reason_code"] == "receipt_binding_mismatch"
    assert _receipt_bindings(config.cache_db_path, event.id) == bindings_before
    assert _projection_snapshot(config.cache_db_path) == projection_before
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event.id
    ]
    assert (attempts[-1]["outcome"], attempts[-1]["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )
    _private_values_absent(config, caplog, (account_id, object_id))


async def test_replay_rejects_bound_scope_disagreement(
    tmp_path,
    caplog,
):
    account_id = "cus_scope_binding_private"
    object_id = "sub_scope_binding_private"
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(config, "Scope Binding")
    admin = await provision_identity(
        config,
        "Scope Binding Admin",
        internal_role="platform_admin",
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id=account_id,
    )
    store = EntitlementStore(config.cache_db_path)
    active = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_scope_binding_active",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id=object_id,
        external_customer_id=account_id,
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=datetime.now(UTC) + timedelta(days=30),
        occurred_at=datetime.fromtimestamp(100, UTC),
        subject_user_id=users[0].id,
    )
    assert active.grant is not None
    auth, _, tokens = _issue_tokens(config, workspace, users)
    occurred_at = datetime.fromtimestamp(200, UTC).isoformat()
    normalized = json.dumps(
        {
            "provider": "stripe",
            "event_id": "evt_scope_binding_cancel",
            "event_type": "customer.subscription.deleted",
            "occurred_at": occurred_at,
            "action": "cancel",
            "external_account_id": account_id,
            "external_object_id": object_id,
            "subscription_status": "canceled",
            "mapping_keys": [],
            "current_period_end": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO platform_provider_events(
                workspace_id,provider,event_id,event_type,payload,
                normalized_data,occurred_at,outcome,reason_code,
                duplicate_count,replayed_at,object_stream_hash,
                restrictive_rank,canonical_action,external_account_hash,
                bound_subject_user_id,bound_scope,created_at,updated_at
            ) VALUES (
                ?,'stripe','evt_scope_binding_cancel',
                'customer.subscription.deleted','{}',?,?,
                'quarantined','projection_failure',0,NULL,?,1,'cancel',?,
                ?,'workspace',?,?
            )
            """,
            (
                workspace.id,
                normalized,
                occurred_at,
                _provider_hash("stripe", object_id),
                _provider_hash("stripe", account_id),
                users[0].id,
                now,
                now,
            ),
        )
        event_id = int(cursor.lastrowid)
    bindings_before = _receipt_bindings(config.cache_db_path, event_id)
    projection_before = _projection_snapshot(config.cache_db_path)

    caplog.set_level(logging.WARNING)
    result = _replay(config, admin.user_id, event_id)

    assert result["outcome"] == "quarantined"
    assert result["reason_code"] == "receipt_binding_mismatch"
    assert _receipt_bindings(config.cache_db_path, event_id) == bindings_before
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert auth.validate_access(tokens[0].access_token) is not None
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_id
    ]
    assert attempts[-1]["reason_code"] == "receipt_binding_mismatch"
    _private_values_absent(config, caplog, (account_id, object_id))


async def test_older_restrictive_replay_after_newer_positive_stays_stale(
    tmp_path,
):
    account_id = "cus_stale_preservation_private"
    object_id = "sub_stale_preservation_private"
    (
        config,
        workspace,
        users,
        _admin,
        store,
        _active,
        auth,
        tokens,
        event,
    ) = await _failed_legacy_cancel(
        tmp_path,
        name="Stale Replay Preservation",
        account_id=account_id,
        object_id=object_id,
        active_at=100,
        cancel_at=200,
    )
    newer = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_stale_preservation_newer",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id=object_id,
        external_customer_id=account_id,
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=datetime.now(UTC) + timedelta(days=30),
        occurred_at=datetime.fromtimestamp(300, UTC),
        subject_user_id=users[0].id,
    )
    assert newer.outcome == "applied"
    projection_before = _projection_snapshot(config.cache_db_path)

    service = ProviderSyncService(config)
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        replay = service.replay_tx(connection, event.id)
        connection.commit()

    assert replay.outcome == "stale"
    assert replay.reason_code == "older_source_event"
    assert _projection_snapshot(config.cache_db_path) == projection_before
    assert auth.validate_access(tokens[0].access_token) is not None
    subscription = store.get_subscription(workspace.id, "stripe", object_id)
    grant = store.get_grant(workspace.id, newer.grant.id)
    account = store.get_account(workspace.id)
    assert subscription is not None and subscription.status == "active"
    assert grant is not None and grant.status == "active"
    assert account is not None and account.state == "active"


async def test_untrusted_legacy_receipt_replay_stays_durably_quarantined(
    tmp_path,
    caplog,
):
    account_id = "cus_untrusted_legacy_private"
    object_id = "sub_untrusted_legacy_private"
    config = provider_config(tmp_path)
    workspace, _users = await _workspace_with_users(
        config,
        "Untrusted Legacy Receipt",
    )
    admin = await provision_identity(
        config,
        "Untrusted Legacy Receipt Admin",
        internal_role="platform_admin",
    )
    occurred_at = datetime.fromtimestamp(200, UTC).isoformat()
    normalized = json.dumps(
        {
            "provider": "stripe",
            "event_id": "evt_untrusted_legacy",
            "event_type": "customer.subscription.deleted",
            "occurred_at": occurred_at,
            "action": "cancel",
            "external_account_id": account_id,
            "external_object_id": object_id,
            "subscription_status": "canceled",
            "mapping_keys": [],
            "current_period_end": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        event_id = int(
            connection.execute(
                """
                INSERT INTO platform_provider_events(
                    workspace_id,provider,event_id,event_type,payload,
                    normalized_data,occurred_at,outcome,reason_code,
                    duplicate_count,replayed_at,object_stream_hash,
                    restrictive_rank,canonical_action,external_account_hash,
                    bound_subject_user_id,bound_scope,created_at,updated_at
                ) VALUES (
                    ?,'stripe','evt_untrusted_legacy',
                    'customer.subscription.deleted','{}',?,?,
                    'quarantined','legacy_receipt_binding_untrusted',
                    0,NULL,NULL,1,'cancel',NULL,NULL,NULL,?,?
                ) RETURNING id
                """,
                (workspace.id, normalized, occurred_at, now, now),
            ).fetchone()[0]
        )
    bindings_before = _receipt_bindings(config.cache_db_path, event_id)
    projection_before = _projection_snapshot(config.cache_db_path)

    caplog.set_level(logging.WARNING)
    result = _replay(config, admin.user_id, event_id)

    assert result["outcome"] == "quarantined"
    assert result["reason_code"] == "legacy_receipt_binding_untrusted"
    assert _receipt_bindings(config.cache_db_path, event_id) == bindings_before
    assert _projection_snapshot(config.cache_db_path) == projection_before
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_id
    ]
    assert (attempts[-1]["outcome"], attempts[-1]["reason_code"]) == (
        "quarantined",
        "legacy_receipt_binding_untrusted",
    )
    _private_values_absent(config, caplog, (account_id, object_id))


async def test_fully_bound_valid_replay_reconciles(
    tmp_path,
):
    account_id = "cus_valid_binding_private"
    object_id = "sub_valid_binding_private"
    (
        config,
        workspace,
        users,
        _admin,
        store,
        _active,
        _auth,
        _tokens,
        event,
    ) = await _failed_legacy_cancel(
        tmp_path,
        name="Valid Replay Binding",
        account_id=account_id,
        object_id=object_id,
    )

    service = ProviderSyncService(config)
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        replay = service.replay_tx(connection, event.id)
        connection.commit()

    bindings = _receipt_bindings(config.cache_db_path, event.id)
    assert replay.outcome == "reconciled"
    assert set(RECEIPT_BINDING_COLUMNS) == set(bindings)
    assert bindings["workspace_id"] == workspace.id
    assert bindings["canonical_action"] == "cancel"
    assert bindings["external_account_hash"] == _provider_hash(
        "stripe",
        account_id,
    )
    assert bindings["object_stream_hash"] == _provider_hash(
        "stripe",
        object_id,
    )
    assert bindings["bound_subject_user_id"] == users[0].id
    assert bindings["bound_scope"] == "subject"
    subscription = store.get_subscription(workspace.id, "stripe", object_id)
    assert subscription is not None and subscription.status == "canceled"
