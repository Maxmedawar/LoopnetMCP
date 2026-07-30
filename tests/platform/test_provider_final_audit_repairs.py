"""Focused red-first regressions for the final provider audit."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.providers.core import ProviderSyncService
from cre_mcp.platform.providers.reconciliation import ProviderReconciliationStore

from .admin_helpers import (
    VALID_REASON,
    audit_rows,
    provision_identity,
    provision_target,
)
from .provider_helpers import (
    api_client,
    provider_attempts,
    provider_config,
    provider_events,
    seed_workspace,
    skool_event,
    stripe_event,
)
from .test_provider_security_repairs import (
    REDIRECT,
    SCOPES,
    _future_period,
    _insert_mapping,
    _issue_tokens,
    _post,
    _workspace_with_users,
)


async def test_stripe_current_period_end_is_authoritative_for_paid_grant(
    tmp_path,
):
    config = provider_config(tmp_path, provider_grant_lease_seconds=60)
    workspace = await seed_workspace(
        config,
        "Authoritative Stripe Period",
        stripe_customer="cus_authoritative_period",
    )
    period_end = datetime.now(UTC) + timedelta(days=30)

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_authoritative_period",
            customer="cus_authoritative_period",
            period_end=int(period_end.timestamp()),
        ),
    )

    assert response.status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        stored = connection.execute(
            """
            SELECT ends_at FROM platform_access_grants
            WHERE workspace_id=? AND source='stripe'
            """,
            (workspace.id,),
        ).fetchone()[0]
    assert abs(
        (
            datetime.fromisoformat(str(stored))
            - datetime.fromtimestamp(int(period_end.timestamp()), UTC)
        ).total_seconds()
    ) < 1


@pytest.mark.parametrize("provider", ["stripe", "skool"])
@pytest.mark.parametrize("restrictive_first", [False, True])
async def test_equal_timestamp_restrictive_event_wins_both_delivery_orders(
    tmp_path,
    provider,
    restrictive_first,
):
    config = provider_config(tmp_path)
    customer = f"cus_equal_rank_{provider}_{int(restrictive_first)}"
    member = f"member_equal_rank_{provider}_{int(restrictive_first)}"
    workspace = await seed_workspace(
        config,
        f"Equal rank {provider} {restrictive_first}",
        stripe_customer=customer if provider == "stripe" else None,
        skool_member=member if provider == "skool" else None,
    )
    if provider == "stripe":
        bootstrap = stripe_event(
            f"evt_rank_bootstrap_{int(restrictive_first)}",
            customer=customer,
            created=50,
            period_end=_future_period(),
        )
        positive = stripe_event(
            f"evt_rank_positive_{int(restrictive_first)}",
            customer=customer,
            created=200,
            period_end=_future_period(),
        )
        restrictive = stripe_event(
            f"evt_rank_cancel_{int(restrictive_first)}",
            event_type="customer.subscription.deleted",
            customer=customer,
            status="canceled",
            created=200,
        )
    else:
        bootstrap = skool_event(
            f"sk_rank_bootstrap_{int(restrictive_first)}",
            event_type="member.added",
            member_id=member,
            created=50,
        )
        positive = skool_event(
            f"sk_rank_positive_{int(restrictive_first)}",
            event_type="member.updated",
            member_id=member,
            created=200,
        )
        restrictive = skool_event(
            f"sk_rank_cancel_{int(restrictive_first)}",
            event_type="member.canceled",
            member_id=member,
            created=200,
        )

    assert (await _post(config, provider, bootstrap)).status_code == 200
    first, second = (
        (restrictive, positive)
        if restrictive_first
        else (positive, restrictive)
    )
    assert (await _post(config, provider, first)).status_code == 200
    delivered_last = await _post(config, provider, second)

    assert delivered_last.status_code == 200
    if restrictive_first:
        assert delivered_last.json()["outcome"] == "stale"
    with sqlite3.connect(config.cache_db_path) as connection:
        grant = connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE workspace_id=? AND source=?
            """,
            (workspace.id, provider),
        ).fetchone()
    assert grant is not None
    assert grant[0] == "revoked"


async def test_stripe_trialing_is_explicitly_non_granting_but_active_grants(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Paid Means Paid",
        stripe_customer="cus_paid_means_paid",
    )

    trialing = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_trialing_not_paid",
            customer="cus_paid_means_paid",
            status="trialing",
            created=100,
            period_end=_future_period(),
        ),
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        trial_grants = connection.execute(
            """
            SELECT COUNT(*) FROM platform_access_grants
            WHERE workspace_id=? AND source='stripe'
              AND status IN ('active','overridden','expiring')
            """,
            (workspace.id,),
        ).fetchone()[0]

    assert trialing.status_code == 200
    assert trialing.json()["outcome"] == "rejected"
    assert trialing.json()["reason_code"] == "trialing_not_paid"
    assert trial_grants == 0

    active = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_paid_active",
            customer="cus_paid_means_paid",
            status="active",
            created=101,
            period_end=_future_period(),
        ),
    )
    assert active.status_code == 200
    assert active.json()["outcome"] == "applied"
    store = EntitlementStore(config.cache_db_path)
    grant = next(
        grant
        for grant in store.list_grants(workspace.id)
        if grant.source == "stripe"
    )
    assert grant.subject_user_id is not None
    assert store.effective_access(
        workspace.id,
        subject_user_id=grant.subject_user_id,
    ) is not None


async def test_restrictive_projection_retries_twice_then_revokes_exact_subject(
    tmp_path,
    monkeypatch,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Restrictive Retry Success",
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_retry_success",
    )
    auth, client_registration, tokens = _issue_tokens(config, workspace, users)
    verifier = "r" * 43
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    pending_code = auth.create_auth_code(
        workspace.public_id,
        users[0].id,
        client_registration.client_id,
        REDIRECT,
        challenge,
        scopes=SCOPES,
    )
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_retry_success_active",
                customer="cus_retry_success",
                created=100,
                period_end=_future_period(),
            ),
        )
    ).status_code == 200

    original = ProviderSyncService._projection_tx
    failures = 0

    def fail_twice(self, *args, **kwargs):
        nonlocal failures
        event = args[1]
        if event.event_id == "evt_retry_success_cancel" and failures < 2:
            failures += 1
            raise sqlite3.OperationalError("injected transient projection error")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ProviderSyncService, "_projection_tx", fail_twice)
    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_retry_success_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_retry_success",
            status="canceled",
            created=200,
        ),
    )

    assert canceled.status_code == 200
    assert canceled.json()["outcome"] == "applied"
    assert failures == 2
    assert auth.validate_access(tokens[0].access_token) is None
    assert auth.validate_access(tokens[1].access_token) is not None
    assert (
        auth.refresh_session(
            tokens[0].refresh_token,
            client_id=client_registration.client_id,
        )
        is None
    )
    with pytest.raises(ValueError, match="invalid or expired authorization code"):
        auth.exchange_code(
            pending_code,
            client_registration.client_id,
            REDIRECT,
            verifier,
        )
    target_id = provider_events(config.cache_db_path)[-1]["id"]
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == target_id
    ]
    assert [row["outcome"] for row in attempts] == [
        "failure",
        "failure",
        "applied",
    ]


async def test_restrictive_projection_retry_exhaustion_is_bounded_and_replayable(
    tmp_path,
    monkeypatch,
    caplog,
):
    config = provider_config(tmp_path)
    await seed_workspace(
        config,
        "Restrictive Retry Exhaustion",
        stripe_customer="cus_retry_exhausted",
    )
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_retry_exhausted_active",
                customer="cus_retry_exhausted",
                created=100,
            ),
        )
    ).status_code == 200
    original = ProviderSyncService._projection_tx
    failures = 0

    def fail_always(self, *args, **kwargs):
        nonlocal failures
        event = args[1]
        if event.event_id == "evt_retry_exhausted_cancel":
            failures += 1
            raise sqlite3.OperationalError("injected persistent projection error")
        return original(self, *args, **kwargs)

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(ProviderSyncService, "_projection_tx", fail_always)
    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_retry_exhausted_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_retry_exhausted",
            status="canceled",
            created=200,
        ),
    )

    assert response.status_code == 202
    assert response.json()["outcome"] == "quarantined"
    assert failures == 3
    event_row = provider_events(config.cache_db_path)[-1]
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_row["id"]
    ]
    assert len(attempts) == 3
    assert {row["reason_code"] for row in attempts} == {"projection_failure"}
    assert "provider_restrictive_retry_exhausted" in caplog.text

    monkeypatch.setattr(ProviderSyncService, "_projection_tx", original)
    service = ProviderSyncService(config)
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        replay = service.replay_tx(connection, int(event_row["id"]))
        connection.commit()

    assert replay.outcome == "reconciled"
    with sqlite3.connect(config.cache_db_path) as connection:
        assert connection.execute(
            """
            SELECT status FROM platform_access_grants
            WHERE source='stripe' AND external_ref='sub_1'
            """
        ).fetchone()[0] == "revoked"


async def test_admin_grants_require_explicit_subject_or_explicit_jv_workspace(
    tmp_path,
):
    config = provider_config(tmp_path)
    actor = await provision_identity(
        config,
        "Scoped Grant Admin",
        internal_role="platform_admin",
    )
    target = await provision_target(config, "Scoped Grant Target")
    path = f"/v1/admin/workspaces/{target.workspace_id}/grants"

    async with api_client(config) as client:
        missing_subject = await client.post(
            path,
            headers=actor.headers,
            json={
                "source": "manual",
                "external_ref": "manual-missing-subject",
                "profile": "full_operator",
                "plan_key": "operator",
                **VALID_REASON,
            },
        )
        subject = await client.post(
            path,
            headers=actor.headers,
            json={
                "source": "promotion",
                "external_ref": "promotion-subject",
                "profile": "local_scout",
                "plan_key": "local",
                "scope": "subject",
                "subject_user_id": target.user_id,
                **VALID_REASON,
            },
        )
        workspace = await client.post(
            path,
            headers=actor.headers,
            json={
                "source": "jv",
                "external_ref": "jv-explicit-workspace",
                "profile": "jv_partner",
                "plan_key": "jv",
                "scope": "workspace",
                **VALID_REASON,
            },
        )

    assert missing_subject.status_code == 422
    assert subject.status_code == 201
    assert subject.json()["grant"]["scope"] == "subject"
    assert subject.json()["grant"]["subject_user_id"] == target.user_id
    assert workspace.status_code == 201
    assert workspace.json()["grant"]["scope"] == "workspace"
    assert workspace.json()["grant"]["subject_user_id"] is None


async def test_authority_uses_grant_scope_not_source_shortcuts(tmp_path):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Authoritative Grant Scope",
        user_count=2,
    )
    store = EntitlementStore(config.cache_db_path)
    store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="manual-exact-subject",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        subject_user_id=users[0].id,
        scope="subject",
    )
    _, _, tokens = _issue_tokens(config, workspace, users)

    async with api_client(config) as client:
        first = await client.get(
            "/v1/deals",
            headers={"authorization": f"Bearer {tokens[0].access_token}"},
        )
        second = await client.get(
            "/v1/deals",
            headers={"authorization": f"Bearer {tokens[1].access_token}"},
        )
    assert first.status_code == 200
    assert second.status_code == 403

    with sqlite3.connect(config.cache_db_path) as connection:
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """
            INSERT INTO platform_plans(
                key,name,daily_quotas,created_at,updated_at
            ) VALUES ('jv','JV','{}',?,?)
            """,
            (now, now),
        )
    store.grant_access(
        workspace=workspace.id,
        source="jv",
        external_ref="jv-explicit-workspace-authority",
        profile=Profile.JV_PARTNER,
        plan_key="jv",
        scope="workspace",
    )
    async with api_client(config) as client:
        second_after_jv = await client.get(
            "/v1/deals",
            headers={"authorization": f"Bearer {tokens[1].access_token}"},
        )
    assert second_after_jv.status_code == 200


async def test_other_users_subject_grant_does_not_survive_provider_churn(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Exact Subject Churn",
        user_count=2,
    )
    _insert_mapping(
        config.cache_db_path,
        workspace_id=workspace.id,
        subject_user_id=users[0].id,
        provider="stripe",
        external_account_id="cus_exact_subject_churn",
    )
    store = EntitlementStore(config.cache_db_path)
    store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="manual-other-subject",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        subject_user_id=users[1].id,
        scope="subject",
    )
    auth, client_registration, tokens = _issue_tokens(config, workspace, users)
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_exact_subject_churn_active",
                customer="cus_exact_subject_churn",
                created=100,
            ),
        )
    ).status_code == 200

    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_exact_subject_churn_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_exact_subject_churn",
            status="canceled",
            created=200,
        ),
    )

    assert canceled.status_code == 200
    assert auth.validate_access(tokens[0].access_token) is None
    assert auth.validate_access(tokens[1].access_token) is not None
    assert (
        auth.refresh_session(
            tokens[0].refresh_token,
            client_id=client_registration.client_id,
        )
        is None
    )


async def test_provider_event_stream_hash_rank_and_covering_index_are_private(
    tmp_path,
):
    config = provider_config(tmp_path)
    await seed_workspace(
        config,
        "Indexed Object Stream",
        stripe_customer="cus_indexed_stream",
    )
    raw_object_id = "sub_private_index_value"
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_indexed_stream",
                object_id=raw_object_id,
                customer="cus_indexed_stream",
                created=100,
            ),
        )
    ).status_code == 200
    expected_hash = hashlib.sha256(
        f"stripe\0{raw_object_id}".encode()
    ).hexdigest()

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT object_stream_hash,restrictive_rank
            FROM platform_provider_events
            WHERE event_id='evt_indexed_stream'
            """
        ).fetchone()
        indexes = {
            str(index[1])
            for index in connection.execute(
                "PRAGMA index_list(platform_provider_events)"
            )
        }
        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT occurred_at,restrictive_rank
            FROM platform_provider_events
            WHERE provider=? AND object_stream_hash=? AND id<>?
            ORDER BY occurred_at DESC,restrictive_rank DESC,id DESC
            LIMIT 1
            """,
            ("stripe", expected_hash, 999999),
        ).fetchall()

    assert row["object_stream_hash"] == expected_hash
    assert row["object_stream_hash"] != raw_object_id
    assert row["restrictive_rank"] == 0
    assert "idx_platform_provider_event_stream_order" in indexes
    assert any(
        "idx_platform_provider_event_stream_order" in str(item["detail"])
        for item in plan
    )


async def test_legacy_restrictive_projection_exhaustion_is_replayable(
    tmp_path,
    caplog,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Legacy Restrictive Replay",
    )
    store = EntitlementStore(config.cache_db_path)
    active = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_legacy_active",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_legacy_replay",
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        subject_user_id=users[0].id,
    )
    assert active.outcome == "applied"

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_legacy_cancellation
            BEFORE UPDATE OF status ON platform_subscriptions
            WHEN NEW.status='canceled'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'injected legacy restrictive projection failure'
                );
            END
            """
        )

    caplog.set_level(logging.ERROR)
    canceled = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_legacy_cancel",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_legacy_replay",
        subscription_status="canceled",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        subject_user_id=users[0].id,
    )

    event_row = next(
        event
        for event in store.list_events(workspace.id)
        if event.event_id == "evt_legacy_cancel"
    )
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_row.id
    ]
    assert canceled.outcome == "quarantined"
    assert [row["reason_code"] for row in attempts] == [
        "projection_failure",
        "projection_failure",
        "projection_failure",
    ]
    assert "provider_restrictive_retry_exhausted" in caplog.text
    assert event_row.payload == {}
    assert event_row.normalized_data["action"] == "cancel"
    assert (
        event_row.normalized_data["external_object_id"]
        == "sub_legacy_replay"
    )

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("DROP TRIGGER reject_legacy_cancellation")
    service = ProviderSyncService(config)
    with service._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        replay = service.replay_tx(connection, event_row.id)
        connection.commit()

    assert replay.outcome == "reconciled"
    assert store.get_subscription(
        workspace.id,
        "stripe",
        "sub_legacy_replay",
    ).status == "canceled"
    grant = store.get_grant(workspace.id, active.grant.id)
    assert grant is not None
    assert grant.status == "revoked"
    assert (
        store.effective_access(
            workspace.id,
            subject_user_id=users[0].id,
        )
        is None
    )


async def test_replay_rejects_forged_cross_workspace_receipt_binding(
    tmp_path,
    caplog,
):
    config = provider_config(tmp_path)
    origin, origin_users = await _workspace_with_users(
        config,
        "Replay Binding Origin",
    )
    victim, victim_users = await _workspace_with_users(
        config,
        "Replay Binding Victim",
    )
    admin = await provision_identity(
        config,
        "Replay Binding Admin",
        internal_role="platform_admin",
    )
    store = EntitlementStore(config.cache_db_path)
    period_end = datetime.now(UTC) + timedelta(days=30)
    origin_active = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_binding_origin_active",
        event_type="customer.subscription.updated",
        workspace=origin.id,
        external_subscription_id="sub_binding_origin",
        external_customer_id="cus_binding_origin",
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=period_end,
        subject_user_id=origin_users[0].id,
    )
    victim_active = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_binding_victim_active",
        event_type="customer.subscription.updated",
        workspace=victim.id,
        external_subscription_id="sub_binding_victim",
        external_customer_id="cus_binding_victim",
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=period_end,
        subject_user_id=victim_users[0].id,
    )
    assert origin_active.grant is not None
    assert victim_active.grant is not None
    origin_auth, _, origin_tokens = _issue_tokens(config, origin, origin_users)
    victim_auth, _, victim_tokens = _issue_tokens(config, victim, victim_users)
    _insert_mapping(
        config.cache_db_path,
        workspace_id=victim.id,
        subject_user_id=victim_users[0].id,
        provider="stripe",
        external_account_id="cus_binding_victim",
    )

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_binding_origin_cancellation
            BEFORE UPDATE OF status ON platform_subscriptions
            WHEN OLD.external_subscription_id='sub_binding_origin'
             AND NEW.status='canceled'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'injected receipt binding projection failure'
                );
            END
            """
        )
    canceled = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_binding_origin_cancel",
        event_type="customer.subscription.deleted",
        workspace=origin.id,
        external_subscription_id="sub_binding_origin",
        external_customer_id="cus_binding_origin",
        subscription_status="canceled",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        subject_user_id=origin_users[0].id,
    )
    assert canceled.outcome == "quarantined"
    event_row = next(
        event
        for event in store.list_events(origin.id)
        if event.event_id == "evt_binding_origin_cancel"
    )
    attempts_before = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_row.id
    ]
    assert [row["reason_code"] for row in attempts_before] == [
        "projection_failure",
        "projection_failure",
        "projection_failure",
    ]

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("DROP TRIGGER reject_binding_origin_cancellation")
        receipt_before = connection.execute(
            """
            SELECT workspace_id,provider,event_id,event_type,occurred_at,
                   object_stream_hash,restrictive_rank,normalized_data
            FROM platform_provider_events
            WHERE id=?
            """,
            (event_row.id,),
        ).fetchone()
        assert receipt_before is not None
        forged = json.loads(str(receipt_before["normalized_data"]))
        forged["external_account_id"] = "cus_binding_victim"
        forged["external_object_id"] = "sub_binding_victim"
        connection.execute(
            """
            UPDATE platform_provider_events
            SET normalized_data=?
            WHERE id=?
            """,
            (
                json.dumps(forged, sort_keys=True, separators=(",", ":")),
                event_row.id,
            ),
        )

    caplog.set_level(logging.WARNING)
    replay = ProviderReconciliationStore(
        config.cache_db_path,
        ProviderSyncService(config),
    ).replay(
        actor_user_id=admin.user_id,
        provider_event_id=event_row.id,
        reason_code=VALID_REASON["reason_code"],
        reason=VALID_REASON["reason"],
    )

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        receipt_after = connection.execute(
            """
            SELECT workspace_id,provider,event_id,event_type,occurred_at,
                   object_stream_hash,restrictive_rank,outcome,reason_code
            FROM platform_provider_events
            WHERE id=?
            """,
            (event_row.id,),
        ).fetchone()
        origin_grant = connection.execute(
            "SELECT status FROM platform_access_grants WHERE id=?",
            (origin_active.grant.id,),
        ).fetchone()
        victim_grant = connection.execute(
            "SELECT status FROM platform_access_grants WHERE id=?",
            (victim_active.grant.id,),
        ).fetchone()
    assert receipt_after is not None
    assert origin_grant is not None
    assert victim_grant is not None
    attempts_after = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_row.id
    ]
    observed = {
        "replay_outcome": replay["outcome"],
        "replay_reason": replay["reason_code"],
        "receipt_workspace": int(receipt_after["workspace_id"]),
        "receipt_outcome": str(receipt_after["outcome"]),
        "receipt_reason": str(receipt_after["reason_code"]),
        "origin_grant": str(origin_grant["status"]),
        "victim_grant": str(victim_grant["status"]),
        "origin_token_valid": (
            origin_auth.validate_access(origin_tokens[0].access_token) is not None
        ),
        "victim_token_valid": (
            victim_auth.validate_access(victim_tokens[0].access_token) is not None
        ),
        "last_attempt": (
            str(attempts_after[-1]["outcome"]),
            str(attempts_after[-1]["reason_code"]),
        ),
    }
    assert observed == {
        "replay_outcome": "quarantined",
        "replay_reason": "receipt_binding_mismatch",
        "receipt_workspace": origin.id,
        "receipt_outcome": "quarantined",
        "receipt_reason": "receipt_binding_mismatch",
        "origin_grant": "active",
        "victim_grant": "active",
        "origin_token_valid": True,
        "victim_token_valid": True,
        "last_attempt": ("quarantined", "receipt_binding_mismatch"),
    }
    for column in (
        "workspace_id",
        "provider",
        "event_id",
        "event_type",
        "occurred_at",
        "object_stream_hash",
        "restrictive_rank",
    ):
        assert receipt_after[column] == receipt_before[column]
    audits = audit_rows(config.cache_db_path)
    assert audits[-1]["action"] == "provider_event.replay"
    assert audits[-1]["workspace_id"] == origin.id
    assert "receipt_binding_mismatch" in str(audits[-1]["after_json"])
    for private_value in (
        "cus_binding_origin",
        "sub_binding_origin",
        "cus_binding_victim",
        "sub_binding_victim",
    ):
        assert private_value not in caplog.text
        assert private_value not in str(audits[-1]["before_json"])
        assert private_value not in str(audits[-1]["after_json"])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("provider", "skool"),
        ("event_id", "evt_binding_forged"),
        ("event_type", "customer.subscription.paused"),
        ("occurred_at", "2030-01-01T00:00:00+00:00"),
        ("action", "activate"),
    ],
)
async def test_replay_rejects_normalized_receipt_identity_mismatch(
    tmp_path,
    field,
    replacement,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        f"Replay Identity {field}",
    )
    admin = await provision_identity(
        config,
        f"Replay Identity Admin {field}",
        internal_role="platform_admin",
    )
    store = EntitlementStore(config.cache_db_path)
    active = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_identity_active",
        event_type="customer.subscription.updated",
        workspace=workspace.id,
        external_subscription_id="sub_identity_binding",
        external_customer_id="cus_identity_binding",
        subscription_status="active",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        current_period_end=datetime.now(UTC) + timedelta(days=30),
        subject_user_id=users[0].id,
    )
    assert active.grant is not None
    auth, _, tokens = _issue_tokens(config, workspace, users)
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_identity_cancellation
            BEFORE UPDATE OF status ON platform_subscriptions
            WHEN OLD.external_subscription_id='sub_identity_binding'
             AND NEW.status='canceled'
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'injected identity binding projection failure'
                );
            END
            """
        )
    canceled = store.apply_subscription_event(
        provider="stripe",
        event_id="evt_identity_cancel",
        event_type="customer.subscription.deleted",
        workspace=workspace.id,
        external_subscription_id="sub_identity_binding",
        external_customer_id="cus_identity_binding",
        subscription_status="canceled",
        plan_key="local",
        profile=Profile.LOCAL_SCOUT,
        subject_user_id=users[0].id,
    )
    assert canceled.outcome == "quarantined"
    event_row = next(
        event
        for event in store.list_events(workspace.id)
        if event.event_id == "evt_identity_cancel"
    )
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("DROP TRIGGER reject_identity_cancellation")
        receipt_before = connection.execute(
            "SELECT * FROM platform_provider_events WHERE id=?",
            (event_row.id,),
        ).fetchone()
        assert receipt_before is not None
        normalized = json.loads(str(receipt_before["normalized_data"]))
        normalized[field] = replacement
        connection.execute(
            "UPDATE platform_provider_events SET normalized_data=? WHERE id=?",
            (
                json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                event_row.id,
            ),
        )

    replay = ProviderReconciliationStore(
        config.cache_db_path,
        ProviderSyncService(config),
    ).replay(
        actor_user_id=admin.user_id,
        provider_event_id=event_row.id,
        reason_code=VALID_REASON["reason_code"],
        reason=VALID_REASON["reason"],
    )

    with sqlite3.connect(config.cache_db_path) as connection:
        connection.row_factory = sqlite3.Row
        receipt_after = connection.execute(
            "SELECT * FROM platform_provider_events WHERE id=?",
            (event_row.id,),
        ).fetchone()
        grant = connection.execute(
            "SELECT status FROM platform_access_grants WHERE id=?",
            (active.grant.id,),
        ).fetchone()
    assert receipt_after is not None
    assert grant is not None
    assert replay["outcome"] == "quarantined"
    assert replay["reason_code"] == "receipt_binding_mismatch"
    assert receipt_after["workspace_id"] == receipt_before["workspace_id"]
    assert receipt_after["provider"] == receipt_before["provider"]
    assert receipt_after["event_id"] == receipt_before["event_id"]
    assert receipt_after["event_type"] == receipt_before["event_type"]
    assert receipt_after["occurred_at"] == receipt_before["occurred_at"]
    assert (
        receipt_after["object_stream_hash"]
        == receipt_before["object_stream_hash"]
    )
    assert str(grant["status"]) == "active"
    assert auth.validate_access(tokens[0].access_token) is not None
    attempts = [
        row
        for row in provider_attempts(config.cache_db_path)
        if row["provider_event_id"] == event_row.id
    ]
    assert (attempts[-1]["outcome"], attempts[-1]["reason_code"]) == (
        "quarantined",
        "receipt_binding_mismatch",
    )


async def test_effective_access_is_exact_subject_plus_explicit_workspace_grants(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Exact Subject Summary",
        user_count=2,
    )
    store = EntitlementStore(config.cache_db_path)
    first = store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="manual-first-subject",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        subject_user_id=users[0].id,
        scope="subject",
    )
    second = store.grant_access(
        workspace=workspace.id,
        source="promotion",
        external_ref="promotion-second-subject",
        profile=Profile.NATIONAL_SCOUT,
        plan_key="national",
        subject_user_id=users[1].id,
        scope="subject",
    )
    shared = store.grant_access(
        workspace=workspace.id,
        source="jv",
        external_ref="jv-explicit-workspace",
        profile=Profile.JV_PARTNER,
        plan_key="local",
        scope="workspace",
    )

    first_access = store.effective_access(
        workspace.id,
        subject_user_id=users[0].id,
    )
    second_access = store.effective_access(
        workspace.id,
        subject_user_id=users[1].id,
    )

    assert first_access is not None
    assert first_access.profile is Profile.FULL_OPERATOR
    assert first_access.plan_key == "operator"
    assert first_access.grant_ids == (first.id, shared.id)
    assert first_access.sources == ("manual", "jv")
    assert second.id not in first_access.grant_ids

    assert second_access is not None
    assert second_access.profile is Profile.NATIONAL_SCOUT
    assert second_access.plan_key == "national"
    assert second_access.grant_ids == (second.id, shared.id)
    assert second_access.sources == ("promotion", "jv")
    assert first.id not in second_access.grant_ids


async def test_entitlement_summary_hides_other_subject_grant_metadata(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace, users = await _workspace_with_users(
        config,
        "Private Entitlement Summary",
        user_count=2,
    )
    store = EntitlementStore(config.cache_db_path)
    store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="manual-private-first",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        subject_user_id=users[0].id,
        scope="subject",
    )
    store.grant_access(
        workspace=workspace.id,
        source="promotion",
        external_ref="promotion-private-second",
        profile=Profile.NATIONAL_SCOUT,
        plan_key="national",
        subject_user_id=users[1].id,
        scope="subject",
    )
    store.grant_access(
        workspace=workspace.id,
        source="jv",
        external_ref="jv-visible-workspace",
        profile=Profile.JV_PARTNER,
        plan_key="local",
        scope="workspace",
    )
    _, _, tokens = _issue_tokens(config, workspace, users)

    async with api_client(config) as client:
        first = await client.get(
            "/v1/entitlements",
            headers={
                "authorization": f"Bearer {tokens[0].access_token}",
            },
        )
        second = await client.get(
            "/v1/entitlements",
            headers={
                "authorization": f"Bearer {tokens[1].access_token}",
            },
        )

    assert first.status_code == 200
    assert {
        (
            grant["source"],
            grant["profile"],
            grant["plan_key"],
            grant["status"],
        )
        for grant in first.json()["grants"]
    } == {
        ("manual", "full_operator", "operator", "active"),
        ("jv", "jv_partner", "local", "active"),
    }
    assert second.status_code == 200
    assert {
        (
            grant["source"],
            grant["profile"],
            grant["plan_key"],
            grant["status"],
        )
        for grant in second.json()["grants"]
    } == {
        ("promotion", "national_scout", "national", "active"),
        ("jv", "jv_partner", "local", "active"),
    }
