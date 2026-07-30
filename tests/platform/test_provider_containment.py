"""Source containment, derived account state, and atomic failure tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.entitlements import EntitlementStore

from .provider_helpers import (
    api_client,
    json_bytes,
    projection,
    provider_attempts,
    provider_config,
    provider_events,
    seed_workspace,
    signed_headers,
    skool_event,
    stripe_event,
)


async def _post(config, provider, event):
    body = json_bytes(event)
    async with api_client(config) as client:
        return await client.post(
            f"/v1/webhooks/{provider}",
            content=body,
            headers=signed_headers(provider, body),
        )


def _subject_id(path, workspace_id: int) -> int:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT user_id
            FROM platform_memberships
            WHERE workspace_id=?
            ORDER BY id
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize(
    "provider,survivor_source",
    [
        ("stripe", "skool"),
        ("stripe", "manual"),
        ("stripe", "jv"),
        ("stripe", "promotion"),
        ("skool", "stripe"),
        ("skool", "manual"),
        ("skool", "jv"),
        ("skool", "promotion"),
    ],
)
async def test_provider_revocation_preserves_every_other_source(
    tmp_path,
    provider,
    survivor_source,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        f"{provider} preserves {survivor_source}",
        stripe_customer="cus_containment",
        skool_member="shared_ref",
    )
    store = EntitlementStore(config.cache_db_path)
    grant_scope = (
        {"scope": "workspace"}
        if survivor_source == "jv"
        else {
            "subject_user_id": _subject_id(
                config.cache_db_path,
                workspace.id,
            ),
            "scope": "subject",
        }
    )
    if survivor_source in {"stripe", "skool"}:
        grant_scope["ends_at"] = datetime.now(UTC) + timedelta(days=30)
    store.grant_access(
        workspace=workspace.id,
        source=survivor_source,
        external_ref="shared_ref",
        profile=Profile.JV_PARTNER
        if survivor_source == "jv"
        else Profile.NATIONAL_SCOUT,
        plan_key="jv" if survivor_source == "jv" else "national",
        **grant_scope,
    )

    if provider == "stripe":
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_containment_start",
                object_id="shared_ref",
                customer="cus_containment",
                created=100,
            ),
        )
        response = await _post(
            config,
            "stripe",
            stripe_event(
                "evt_containment_stop",
                event_type="customer.subscription.deleted",
                object_id="shared_ref",
                customer="cus_containment",
                status="canceled",
                created=200,
            ),
        )
    else:
        await _post(
            config,
            "skool",
            skool_event(
                "sk_containment_start",
                event_type="member.added",
                member_id="shared_ref",
                created=100,
            ),
        )
        response = await _post(
            config,
            "skool",
            skool_event(
                "sk_containment_stop",
                event_type="member.removed",
                member_id="shared_ref",
                created=200,
            ),
        )

    grants = {item.source: item for item in store.list_grants(workspace.id)}
    assert response.status_code == 200
    assert grants[provider].status == "revoked"
    assert grants[survivor_source].status == "active"
    assert store.get_account(workspace.id).state == "active"
    effective = store.effective_access(
        workspace.id,
        subject_user_id=_subject_id(config.cache_db_path, workspace.id),
    )
    assert effective is not None
    assert survivor_source in effective.sources


async def test_canceling_one_of_two_live_stripe_subscriptions_keeps_account_active(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Two Stripe Subscriptions",
        stripe_customer="cus_two",
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_sub_one", object_id="sub_one", customer="cus_two", created=100),
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_sub_two", object_id="sub_two", customer="cus_two", created=200),
    )
    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_cancel_one",
            event_type="customer.subscription.deleted",
            object_id="sub_one",
            customer="cus_two",
            status="canceled",
            created=300,
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    statuses = {grant.external_ref: grant.status for grant in store.list_grants(workspace.id)}
    assert response.status_code == 200
    assert statuses == {"sub_one": "revoked", "sub_two": "active"}
    assert store.get_account(workspace.id).state == "active"


async def test_paused_revokes_only_stripe_and_never_writes_suspended(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Paused",
        stripe_customer="cus_paused",
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_pause_start", customer="cus_paused", created=100),
    )
    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_pause",
            customer="cus_paused",
            status="paused",
            created=200,
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    assert response.status_code == 200
    assert store.list_grants(workspace.id)[0].status == "revoked"
    assert store.get_account(workspace.id).state == "canceled"
    assert store.get_account(workspace.id).state != "suspended"


@pytest.mark.parametrize(
    "state",
    ["suspended", "under_review", "deletion_pending", "deleted"],
)
@pytest.mark.parametrize("provider", ["stripe", "skool"])
async def test_operator_only_states_make_provider_projection_inert(
    tmp_path,
    state,
    provider,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        f"{state} {provider}",
        stripe_customer="cus_operator_state",
        skool_member="member_operator_state",
    )
    store = EntitlementStore(config.cache_db_path)
    store.set_account_state(workspace.id, "active")
    store.set_account_state(workspace.id, state, reason="operator security hold")
    before = projection(config.cache_db_path)
    event = (
        stripe_event(
            f"evt_{state}",
            customer="cus_operator_state",
            prices=("price_operator",),
        )
        if provider == "stripe"
        else skool_event(
            f"sk_{state}",
            event_type="member.added",
            member_id="member_operator_state",
        )
    )

    response = await _post(config, provider, event)

    assert response.status_code == 202
    assert projection(config.cache_db_path) == before
    account = store.get_account(workspace.id)
    assert account.state == state
    assert account.reason == "operator security hold"
    assert provider_events(config.cache_db_path)[0]["reason_code"] == "operator_state"


async def test_restrictive_state_from_invited_fails_closed_without_provider_state(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Invited Transition",
        stripe_customer="cus_invited",
    )
    store = EntitlementStore(config.cache_db_path)
    store.set_account_state(workspace.id, "invited")
    before = projection(config.cache_db_path)

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_invalid_transition",
            customer="cus_invited",
            status="past_due",
        ),
    )

    assert response.status_code == 200
    assert projection(config.cache_db_path) == before
    assert response.json()["outcome"] == "rejected"
    assert provider_events(config.cache_db_path)[0]["reason_code"] == (
        "no_provider_state"
    )


async def test_existing_subscription_workspace_conflict_quarantines(tmp_path):
    config = provider_config(tmp_path)
    mapped = await seed_workspace(
        config,
        "Mapped",
        stripe_customer="cus_conflict",
    )
    other = await seed_workspace(config, "Existing Other")
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            INSERT INTO platform_subscriptions(
                workspace_id,provider,external_subscription_id,
                external_customer_id,status,plan_key,current_period_end,
                last_event_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                other.id,
                "stripe",
                "sub_conflict",
                "cus_conflict",
                "active",
                "local",
                None,
                now,
                now,
                now,
            ),
        )
    before = projection(config.cache_db_path)

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_workspace_conflict",
            object_id="sub_conflict",
            customer="cus_conflict",
        ),
    )

    assert mapped.id != other.id
    assert response.status_code == 202
    assert projection(config.cache_db_path) == before
    assert provider_events(config.cache_db_path)[0]["reason_code"] == "conflicting_mapping"


async def test_expired_survivor_does_not_prevent_derived_cancellation(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Expired Survivor",
        stripe_customer="cus_expired",
    )
    store = EntitlementStore(config.cache_db_path)
    store.grant_access(
        workspace=workspace.id,
        source="manual",
        external_ref="expired",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        ends_at=datetime.now(UTC) - timedelta(seconds=1),
        subject_user_id=_subject_id(config.cache_db_path, workspace.id),
        scope="subject",
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_expired_start", customer="cus_expired", created=100),
    )

    await _post(
        config,
        "stripe",
        stripe_event(
            "evt_expired_stop",
            event_type="customer.subscription.deleted",
            customer="cus_expired",
            status="canceled",
            created=200,
        ),
    )

    assert store.get_account(workspace.id).state == "canceled"
    assert store.effective_access(
        workspace.id,
        subject_user_id=_subject_id(config.cache_db_path, workspace.id),
    ) is None


async def test_projection_trigger_failure_records_payload_free_failure_only(tmp_path):
    config = provider_config(tmp_path)
    await seed_workspace(config, "Induced Failure", stripe_customer="cus_trigger")
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_stripe_grant
            BEFORE INSERT ON platform_access_grants
            WHEN NEW.source='stripe'
            BEGIN
                SELECT RAISE(ABORT, 'injected provider projection failure');
            END
            """
        )
    before = projection(config.cache_db_path)

    response = await _post(
        config,
        "stripe",
        stripe_event("evt_trigger_failure", customer="cus_trigger"),
    )

    assert response.status_code == 202
    assert response.json()["outcome"] == "quarantined"
    assert projection(config.cache_db_path) == before
    assert provider_events(config.cache_db_path)[0]["reason_code"] == "projection_failure"
    assert provider_attempts(config.cache_db_path)[0]["outcome"] == "failure"


async def test_concurrent_identical_receipts_are_applied_once(tmp_path):
    config = provider_config(tmp_path)
    await seed_workspace(config, "Concurrent", stripe_customer="cus_concurrent")
    event = stripe_event("evt_concurrent", customer="cus_concurrent")
    body = json_bytes(event)
    headers = signed_headers("stripe", body)

    async def send():
        async with api_client(config) as client:
            return await client.post(
                "/v1/webhooks/stripe",
                content=body,
                headers=headers,
            )

    first, second = await asyncio.gather(send(), send())

    assert sorted([first.json()["outcome"], second.json()["outcome"]]) == [
        "applied",
        "duplicate",
    ]
    snapshot = projection(config.cache_db_path)
    assert len(snapshot["platform_subscriptions"]) == 1
    assert len(snapshot["platform_access_grants"]) == 1


async def test_skool_remove_without_source_state_preserves_closed_stripe_state(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Stripe Past Due Survivor",
        stripe_customer="cus_past_due_survivor",
        skool_member="member_without_skool_state",
    )
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_past_due_survivor_start",
                customer="cus_past_due_survivor",
                status="active",
                created=100,
            ),
        )
    ).status_code == 200
    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_past_due_survivor_restrict",
                customer="cus_past_due_survivor",
                status="past_due",
                created=200,
            ),
        )
    ).status_code == 200
    before = projection(config.cache_db_path)

    removed = await _post(
        config,
        "skool",
        skool_event(
            "sk_remove_without_state",
            event_type="member.removed",
            member_id="member_without_skool_state",
            created=300,
        ),
    )

    assert removed.status_code == 200
    assert removed.json()["outcome"] == "rejected"
    assert removed.json()["reason_code"] == "no_provider_state"
    assert projection(config.cache_db_path) == before
    account = EntitlementStore(config.cache_db_path).get_account(workspace.id)
    assert account is not None
    assert account.state == "canceled"
    row = provider_events(config.cache_db_path)[-1]
    assert row["outcome"] == "rejected"
    assert row["reason_code"] == "no_provider_state"
    assert provider_attempts(config.cache_db_path)[-1]["reason_code"] == (
        "no_provider_state"
    )


async def test_skool_remove_without_source_state_does_not_create_account(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Empty Skool Removal",
        skool_member="member_empty_removal",
    )
    store = EntitlementStore(config.cache_db_path)
    assert store.get_account(workspace.id) is None
    before = projection(config.cache_db_path)

    removed = await _post(
        config,
        "skool",
        skool_event(
            "sk_empty_remove",
            event_type="member.removed",
            member_id="member_empty_removal",
        ),
    )

    assert removed.status_code == 200
    assert removed.json()["accepted"] is True
    assert removed.json()["outcome"] == "rejected"
    assert removed.json()["reason_code"] == "no_provider_state"
    assert projection(config.cache_db_path) == before
    assert store.get_account(workspace.id) is None


async def test_stripe_cancel_without_source_state_does_not_create_rows(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Empty Stripe Cancellation",
        stripe_customer="cus_empty_cancel",
    )
    store = EntitlementStore(config.cache_db_path)
    before = projection(config.cache_db_path)

    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_empty_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_empty_cancel",
            status="canceled",
        ),
    )

    assert canceled.status_code == 200
    assert canceled.json()["outcome"] == "rejected"
    assert canceled.json()["reason_code"] == "no_provider_state"
    assert projection(config.cache_db_path) == before
    assert store.get_account(workspace.id) is None
    assert store.get_subscription(workspace.id, "stripe", "sub_1") is None


async def test_same_state_provider_projection_preserves_operator_reason(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Preserved Account Reason",
        stripe_customer="cus_preserved_reason",
    )
    store = EntitlementStore(config.cache_db_path)
    store.set_account_state(
        workspace.id,
        "active",
        reason="operator-authored billing note",
    )

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_preserve_account_reason",
            customer="cus_preserved_reason",
            status="active",
        ),
    )

    assert response.status_code == 200
    account = store.get_account(workspace.id)
    assert account is not None
    assert account.state == "active"
    assert account.reason == "operator-authored billing note"
