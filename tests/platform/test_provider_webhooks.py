"""End-to-end offline webhook semantics and durable outcome coverage."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta

import pytest

from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.providers.core import ProviderSyncService

from .provider_helpers import (
    NOW,
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


async def _post(config, provider: str, value: dict):
    body = json_bytes(value)
    async with api_client(config) as client:
        return await client.post(
            f"/v1/webhooks/{provider}",
            content=body,
            headers=signed_headers(provider, body),
        )


async def test_stripe_activation_upgrade_downgrade_and_cancel(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Stripe Lifecycle",
        stripe_customer="cus_lifecycle",
    )

    activated = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_activate",
            customer="cus_lifecycle",
            prices=("price_local",),
            created=100,
        ),
    )
    upgraded = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_upgrade",
            customer="cus_lifecycle",
            prices=("price_operator",),
            created=200,
        ),
    )
    downgraded = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_downgrade",
            customer="cus_lifecycle",
            prices=("price_national",),
            created=300,
        ),
    )
    canceled = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_cancel",
            event_type="customer.subscription.deleted",
            customer="cus_lifecycle",
            status="canceled",
            prices=("price_national",),
            created=400,
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    assert [item.status_code for item in (activated, upgraded, downgraded, canceled)] == [
        200,
        200,
        200,
        200,
    ]
    assert store.get_subscription(
        workspace.id,
        "stripe",
        "sub_1",
    ).status == "canceled"
    assert store.list_grants(workspace.id)[0].status == "revoked"
    assert store.get_account(workspace.id).state == "canceled"
    assert [row["outcome"] for row in provider_events(config.cache_db_path)] == [
        "applied",
        "applied",
        "applied",
        "applied",
    ]


async def test_duplicate_receipt_records_attempt_and_changes_no_projection(tmp_path):
    config = provider_config(tmp_path)
    await seed_workspace(config, "Duplicate", stripe_customer="cus_dup")
    event = stripe_event("evt_duplicate", customer="cus_dup")

    first = await _post(config, "stripe", event)
    before = projection(config.cache_db_path)
    duplicate_value = stripe_event(
        "evt_duplicate",
        customer="cus_dup",
        status="canceled",
        prices=("price_operator",),
    )
    duplicate = await _post(config, "stripe", duplicate_value)
    after = projection(config.cache_db_path)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "duplicate"
    assert before == after
    assert len(provider_events(config.cache_db_path)) == 1
    assert [row["outcome"] for row in provider_attempts(config.cache_db_path)] == [
        "applied",
        "duplicate",
    ]
    assert provider_events(config.cache_db_path)[0]["outcome"] == "applied"


async def test_stale_event_is_explicit_and_projection_non_mutating(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Stale",
        stripe_customer="cus_stale",
    )
    newer = stripe_event(
        "evt_newer",
        customer="cus_stale",
        created=200,
        status="canceled",
        event_type="customer.subscription.deleted",
    )
    older = stripe_event(
        "evt_older",
        customer="cus_stale",
        created=100,
        status="active",
        prices=("price_operator",),
    )

    assert (
        await _post(
            config,
            "stripe",
            stripe_event(
                "evt_stale_bootstrap",
                customer="cus_stale",
                created=50,
            ),
        )
    ).status_code == 200
    assert (await _post(config, "stripe", newer)).status_code == 200
    assert EntitlementStore(config.cache_db_path).get_account(
        workspace.id
    ).state == "canceled"
    before = projection(config.cache_db_path)
    response = await _post(config, "stripe", older)

    assert response.status_code == 200
    assert response.json()["outcome"] == "stale"
    assert projection(config.cache_db_path) == before
    assert provider_events(config.cache_db_path)[-1]["outcome"] == "stale"


async def test_equal_timestamps_apply_in_receipt_order(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(config, "Equal", stripe_customer="cus_equal")
    active = stripe_event("evt_equal_active", customer="cus_equal", created=100)
    canceled = stripe_event(
        "evt_equal_cancel",
        customer="cus_equal",
        created=100,
        event_type="customer.subscription.deleted",
        status="canceled",
    )

    assert (await _post(config, "stripe", active)).json()["outcome"] == "applied"
    assert (await _post(config, "stripe", canceled)).json()["outcome"] == "applied"

    store = EntitlementStore(config.cache_db_path)
    assert store.get_subscription(workspace.id, "stripe", "sub_1").status == "canceled"


async def test_no_state_restriction_orders_older_activation_without_rows(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "No State Ordering",
        stripe_customer="cus_no_state_ordering",
    )
    newer_cancel = stripe_event(
        "evt_no_state_newer_cancel",
        customer="cus_no_state_ordering",
        created=200,
        event_type="customer.subscription.deleted",
        status="canceled",
    )
    older_active = stripe_event(
        "evt_no_state_older_active",
        customer="cus_no_state_ordering",
        created=100,
    )
    equal_active = stripe_event(
        "evt_no_state_equal_active",
        customer="cus_no_state_ordering",
        created=200,
    )

    canceled = await _post(config, "stripe", newer_cancel)
    before = projection(config.cache_db_path)
    stale = await _post(config, "stripe", older_active)

    assert canceled.json()["outcome"] == "rejected"
    assert canceled.json()["reason_code"] == "no_provider_state"
    assert stale.json()["outcome"] == "stale"
    assert projection(config.cache_db_path) == before
    assert (
        EntitlementStore(config.cache_db_path).get_subscription(
            workspace.id,
            "stripe",
            "sub_1",
        )
        is None
    )

    equal = await _post(config, "stripe", equal_active)
    assert equal.json()["outcome"] == "applied"
    assert (
        EntitlementStore(config.cache_db_path)
        .get_subscription(workspace.id, "stripe", "sub_1")
        .status
        == "active"
    )


async def test_unmapped_restriction_orders_activation_after_mapping(tmp_path):
    config = provider_config(tmp_path)
    newer_cancel = stripe_event(
        "evt_unmapped_order_newer_cancel",
        customer="cus_unmapped_order",
        object_id="sub_unmapped_order",
        created=200,
        event_type="customer.subscription.deleted",
        status="canceled",
    )
    older_active = stripe_event(
        "evt_unmapped_order_older_active",
        customer="cus_unmapped_order",
        object_id="sub_unmapped_order",
        created=100,
    )
    equal_active = stripe_event(
        "evt_unmapped_order_equal_active",
        customer="cus_unmapped_order",
        object_id="sub_unmapped_order",
        created=200,
    )

    unmapped = await _post(config, "stripe", newer_cancel)
    assert unmapped.status_code == 202
    assert unmapped.json()["reason_code"] == "unmapped_external_account"

    workspace = await seed_workspace(
        config,
        "Unmapped Ordering",
        stripe_customer="cus_unmapped_order",
    )
    before = projection(config.cache_db_path)
    stale = await _post(config, "stripe", older_active)

    assert stale.json()["outcome"] == "stale"
    assert projection(config.cache_db_path) == before
    assert (
        EntitlementStore(config.cache_db_path).get_subscription(
            workspace.id,
            "stripe",
            "sub_unmapped_order",
        )
        is None
    )

    equal = await _post(config, "stripe", equal_active)
    assert equal.json()["outcome"] == "applied"
    assert (
        EntitlementStore(config.cache_db_path)
        .get_subscription(workspace.id, "stripe", "sub_unmapped_order")
        .status
        == "active"
    )


@pytest.mark.parametrize(
    ("mapping_preexists", "failure_reason"),
    [
        (False, "unmapped_external_account"),
        (True, "subscription_not_found"),
    ],
    ids=["cold-unmapped", "mapped-no-subscription"],
)
async def test_invoice_failure_orders_older_activation_by_subscription(
    tmp_path,
    mapping_preexists,
    failure_reason,
):
    config = provider_config(tmp_path)
    customer = f"cus_invoice_order_{int(mapping_preexists)}"
    if mapping_preexists:
        workspace = await seed_workspace(
            config,
            "Mapped Invoice Ordering",
            stripe_customer=customer,
        )

    failed = await _post(
        config,
        "stripe",
        stripe_event(
            f"evt_invoice_order_failed_{int(mapping_preexists)}",
            event_type="invoice.payment_failed",
            object_id=f"in_invoice_order_{int(mapping_preexists)}",
            customer=customer,
            prices=(),
            created=200,
            extra_object={"subscription": "sub_invoice_order"},
        ),
    )
    assert failed.status_code == 202
    assert failed.json()["reason_code"] == failure_reason

    if not mapping_preexists:
        workspace = await seed_workspace(
            config,
            "Cold Invoice Ordering",
            stripe_customer=customer,
        )
    before = projection(config.cache_db_path)
    older = await _post(
        config,
        "stripe",
        stripe_event(
            f"evt_invoice_order_active_{int(mapping_preexists)}",
            object_id="sub_invoice_order",
            customer=customer,
            created=100,
        ),
    )

    stored = provider_events(config.cache_db_path)
    normalized = json.loads(stored[0]["normalized_data"])
    assert normalized["external_object_id"] == "sub_invoice_order"
    assert older.json()["outcome"] == "stale"
    assert projection(config.cache_db_path) == before
    assert (
        EntitlementStore(config.cache_db_path).get_subscription(
            workspace.id,
            "stripe",
            "sub_invoice_order",
        )
        is None
    )


async def test_invoice_failure_ordering_survives_duplicate_and_replay(tmp_path):
    config = provider_config(tmp_path)
    event = stripe_event(
        "evt_invoice_replay_order",
        event_type="invoice.payment_failed",
        object_id="in_invoice_replay_order",
        customer="cus_invoice_replay_order",
        prices=(),
        created=200,
        extra_object={"subscription": "sub_invoice_replay_order"},
    )

    first = await _post(config, "stripe", event)
    duplicate = await _post(config, "stripe", event)
    assert first.status_code == 202
    assert first.json()["reason_code"] == "unmapped_external_account"
    assert duplicate.json()["outcome"] == "duplicate"

    workspace = await seed_workspace(
        config,
        "Invoice Replay Ordering",
        stripe_customer="cus_invoice_replay_order",
    )
    before = projection(config.cache_db_path)
    service = ProviderSyncService(config)
    event_db_id = int(provider_events(config.cache_db_path)[0]["id"])
    replay_results = []
    for _ in range(2):
        with sqlite3.connect(config.cache_db_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            replay_results.append(service.replay_tx(connection, event_db_id))
            connection.commit()

    assert [
        (result.outcome, result.reason_code) for result in replay_results
    ] == [
        ("quarantined", "subscription_not_found"),
        ("quarantined", "subscription_not_found"),
    ]
    assert projection(config.cache_db_path) == before
    stored = provider_events(config.cache_db_path)[0]
    assert stored["duplicate_count"] == 1
    assert stored["replayed_at"] is not None
    assert stored["payload"] == "{}"

    older = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_invoice_replay_older_active",
            object_id="sub_invoice_replay_order",
            customer="cus_invoice_replay_order",
            created=100,
        ),
    )
    assert older.json()["outcome"] == "stale"
    assert projection(config.cache_db_path) == before
    assert (
        EntitlementStore(config.cache_db_path).get_subscription(
            workspace.id,
            "stripe",
            "sub_invoice_replay_order",
        )
        is None
    )


async def test_invoice_failure_ordering_does_not_cross_subscription_streams(
    tmp_path,
):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Invoice Stream Isolation",
        stripe_customer="cus_invoice_streams",
    )
    failed = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_invoice_stream_a_failed",
            event_type="invoice.payment_failed",
            object_id="in_invoice_stream_a",
            customer="cus_invoice_streams",
            prices=(),
            created=200,
            extra_object={"subscription": "sub_invoice_stream_a"},
        ),
    )
    unrelated = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_invoice_stream_b_active",
            object_id="sub_invoice_stream_b",
            customer="cus_invoice_streams",
            created=100,
        ),
    )
    related = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_invoice_stream_a_older_active",
            object_id="sub_invoice_stream_a",
            customer="cus_invoice_streams",
            created=100,
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    assert failed.status_code == 202
    assert failed.json()["reason_code"] == "subscription_not_found"
    assert unrelated.json()["outcome"] == "applied"
    assert related.json()["outcome"] == "stale"
    assert (
        store.get_subscription(
            workspace.id,
            "stripe",
            "sub_invoice_stream_b",
        ).status
        == "active"
    )
    assert (
        store.get_subscription(
            workspace.id,
            "stripe",
            "sub_invoice_stream_a",
        )
        is None
    )


async def test_invoice_failure_without_subscription_correlation_fails_closed(
    tmp_path,
):
    config = provider_config(tmp_path)
    await seed_workspace(
        config,
        "Uncorrelated Invoice",
        stripe_customer="cus_invoice_uncorrelated",
    )
    event = stripe_event(
        "evt_invoice_uncorrelated",
        event_type="invoice.payment_failed",
        object_id="in_invoice_uncorrelated",
        customer="cus_invoice_uncorrelated",
        prices=(),
        created=200,
    )

    first = await _post(config, "stripe", event)
    before = projection(config.cache_db_path)
    duplicate = await _post(config, "stripe", event)

    stored = provider_events(config.cache_db_path)[0]
    assert first.status_code == 202
    assert first.json()["reason_code"] == "missing_subscription_correlation"
    assert duplicate.json()["outcome"] == "duplicate"
    assert projection(config.cache_db_path) == before
    assert stored["payload"] == "{}"
    assert stored["normalized_data"] == "{}"
    assert stored["duplicate_count"] == 1


async def test_invoice_payment_failed_restricts_exact_existing_subscription(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Payment Failure",
        stripe_customer="cus_failed",
    )
    await _post(
        config,
        "stripe",
        stripe_event(
            "evt_subscription",
            customer="cus_failed",
            created=100,
            prices=("price_operator",),
        ),
    )
    failed = stripe_event(
        "evt_failed",
        event_type="invoice.payment_failed",
        object_id="in_failed",
        customer="cus_failed",
        status="open",
        prices=(),
        created=200,
        extra_object={"subscription": "sub_1"},
    )

    response = await _post(config, "stripe", failed)

    store = EntitlementStore(config.cache_db_path)
    assert response.status_code == 200
    assert store.get_subscription(
        workspace.id,
        "stripe",
        "sub_1",
    ).status == "unpaid"
    assert store.list_grants(workspace.id)[0].status == "revoked"
    assert store.get_account(workspace.id).state == "canceled"
    assert store.get_subscription(
        workspace.id,
        "stripe",
        "in_failed",
    ) is None


async def test_invoice_payment_failed_never_creates_and_ambiguous_is_quarantined(
    tmp_path,
):
    config = provider_config(tmp_path)
    await seed_workspace(config, "No Subscription", stripe_customer="cus_none")
    failed = stripe_event(
        "evt_failed_none",
        event_type="invoice.payment_failed",
        object_id="in_none",
        customer="cus_none",
        prices=(),
    )

    response = await _post(config, "stripe", failed)

    assert response.status_code == 202
    assert response.json()["outcome"] == "quarantined"
    snapshot = projection(config.cache_db_path)
    assert snapshot["platform_subscriptions"] == []
    assert snapshot["platform_access_grants"] == []


async def test_invoice_payment_succeeded_never_restores_access(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Succeeded No Restore",
        stripe_customer="cus_succeeded",
    )
    await _post(
        config,
        "stripe",
        stripe_event("evt_start", customer="cus_succeeded", created=100),
    )
    await _post(
        config,
        "stripe",
        stripe_event(
            "evt_stop",
            event_type="customer.subscription.deleted",
            customer="cus_succeeded",
            status="canceled",
            created=200,
        ),
    )
    succeeded = stripe_event(
        "evt_succeeded",
        event_type="invoice.payment_succeeded",
        object_id="in_succeeded",
        customer="cus_succeeded",
        status="paid",
        prices=(),
        created=300,
    )

    response = await _post(config, "stripe", succeeded)

    store = EntitlementStore(config.cache_db_path)
    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert store.get_account(workspace.id).state == "canceled"
    assert store.list_grants(workspace.id)[0].status == "revoked"


async def test_invoice_payment_failed_never_restores_terminal_access(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Failed No Restore",
        stripe_customer="cus_failed_terminal",
    )
    await _post(
        config,
        "stripe",
        stripe_event(
            "evt_terminal_start",
            customer="cus_failed_terminal",
            created=100,
        ),
    )
    await _post(
        config,
        "stripe",
        stripe_event(
            "evt_terminal_stop",
            event_type="customer.subscription.deleted",
            customer="cus_failed_terminal",
            status="canceled",
            created=200,
        ),
    )
    before = projection(config.cache_db_path)
    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_terminal_failed",
            event_type="invoice.payment_failed",
            object_id="in_terminal_failed",
            customer="cus_failed_terminal",
            status="open",
            prices=(),
            created=300,
            extra_object={"subscription": "sub_1"},
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert projection(config.cache_db_path) == before
    assert store.get_account(workspace.id).state == "canceled"
    assert store.list_grants(workspace.id)[0].status == "revoked"


async def test_skool_add_update_and_remove_uses_member_identity(tmp_path):
    config = provider_config(tmp_path)
    workspace = await seed_workspace(
        config,
        "Skool Lifecycle",
        skool_member="member_lifecycle",
    )

    added = await _post(
        config,
        "skool",
        skool_event(
            "sk_add",
            event_type="member.added",
            member_id="member_lifecycle",
            level_id="level_local",
            created=100,
        ),
    )
    updated = await _post(
        config,
        "skool",
        skool_event(
            "sk_update",
            member_id="member_lifecycle",
            level_id="level_national",
            created=200,
        ),
    )
    removed = await _post(
        config,
        "skool",
        skool_event(
            "sk_remove",
            event_type="member.removed",
            member_id="member_lifecycle",
            level_id="level_national",
            created=300,
        ),
    )

    store = EntitlementStore(config.cache_db_path)
    assert [item.status_code for item in (added, updated, removed)] == [200, 200, 200]
    grant = store.list_grants(workspace.id)[0]
    assert grant.source == "skool"
    assert grant.external_ref == "member_lifecycle"
    assert grant.profile.value == "national_scout"
    assert grant.status == "revoked"


@pytest.mark.parametrize(
    "provider,event,reason",
    [
        (
            "stripe",
            stripe_event("evt_unknown_customer", customer="cus_missing"),
            "unmapped_external_account",
        ),
        (
            "stripe",
            stripe_event(
                "evt_unknown_price",
                customer="cus_known",
                prices=("price_missing",),
            ),
            "unmapped_plan",
        ),
        (
            "stripe",
            stripe_event(
                "evt_missing_price",
                customer="cus_known",
                prices=(),
            ),
            "unmapped_plan",
        ),
        (
            "stripe",
            stripe_event(
                "evt_conflicting_prices",
                customer="cus_known",
                prices=("price_local", "price_operator"),
            ),
            "conflicting_plan_mapping",
        ),
        (
            "skool",
            skool_event("sk_unknown_member", member_id="member_missing"),
            "unmapped_external_account",
        ),
        (
            "skool",
            skool_event(
                "sk_unknown_level",
                member_id="member_known",
                level_id="missing",
            ),
            "unmapped_plan",
        ),
        (
            "skool",
            skool_event(
                "sk_unknown_community",
                member_id="member_known",
                community_id="community_missing",
            ),
            "unmapped_plan",
        ),
    ],
)
async def test_mapping_failures_quarantine_without_projection(
    tmp_path,
    provider,
    event,
    reason,
):
    config = provider_config(tmp_path)
    await seed_workspace(
        config,
        f"Mapping {event['id']}",
        stripe_customer="cus_known",
        skool_member="member_known",
    )
    before = projection(config.cache_db_path)

    response = await _post(config, provider, event)

    assert response.status_code == 202
    assert response.json()["outcome"] == "quarantined"
    assert projection(config.cache_db_path) == before
    row = provider_events(config.cache_db_path)[0]
    assert row["outcome"] == "quarantined"
    assert row["reason_code"] == reason
    assert row["workspace_id"] is None or isinstance(row["workspace_id"], int)


async def test_missing_database_plan_quarantines_without_grant(tmp_path):
    config = provider_config(tmp_path)
    await seed_workspace(config, "Missing DB Plan", stripe_customer="cus_plan")
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("DELETE FROM platform_plans WHERE key='operator'")

    response = await _post(
        config,
        "stripe",
        stripe_event(
            "evt_missing_db_plan",
            customer="cus_plan",
            prices=("price_operator",),
        ),
    )

    assert response.status_code == 202
    assert response.json()["outcome"] == "quarantined"
    assert projection(config.cache_db_path)["platform_access_grants"] == []
    assert provider_events(config.cache_db_path)[0]["reason_code"] == "plan_not_found"


async def test_extra_pii_and_raw_payload_are_not_persisted_or_echoed(
    tmp_path,
    caplog,
):
    caplog.set_level(logging.INFO)
    config = provider_config(tmp_path)
    await seed_workspace(config, "Privacy", stripe_customer="cus_privacy")
    pii_email = "private-person-98431@example.test"
    raw_marker = "RAW_BODY_SENTINEL_86e27f"
    event = stripe_event(
        "evt_privacy",
        customer="cus_privacy",
        extra_object={
            "email": pii_email,
            "metadata": {"private": raw_marker},
        },
        extra_envelope={"request": {"id": raw_marker}},
    )
    body = json_bytes(event)

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )

    with sqlite3.connect(config.cache_db_path) as connection:
        dump = "\n".join(connection.iterdump())
    combined = response.text + caplog.text + dump
    assert response.status_code == 200
    assert pii_email not in combined
    assert raw_marker not in combined
    assert body.decode() not in combined


async def test_unsupported_stripe_reason_matches_durable_reason(tmp_path):
    config = provider_config(tmp_path)
    event = stripe_event(
        "evt_unsupported_reason",
        event_type="charge.refunded",
    )

    response = await _post(config, "stripe", event)

    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert response.json()["reason_code"] == "unsupported_event_type"
    row = provider_events(config.cache_db_path)[0]
    assert row["outcome"] == "rejected"
    assert row["reason_code"] == "unsupported_event_type"


async def test_malformed_stripe_salvage_does_not_persist_attacker_type(tmp_path):
    config = provider_config(tmp_path)
    attacker_type = (
        "customer.subscription.private-person-98431@example.test."
        "RAW_TYPE_SENTINEL_71d6"
    )
    leading = json_bytes(
        {
            "id": "evt_attacker_controlled_type",
            "type": attacker_type,
            "created": int(NOW.timestamp()),
        }
    )
    malformed = leading + b"\ntrailing-invalid"

    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=malformed,
            headers=signed_headers("stripe", malformed),
        )

    with sqlite3.connect(config.cache_db_path) as connection:
        dump = "\n".join(connection.iterdump())
    assert response.status_code == 400
    assert attacker_type not in response.text
    assert attacker_type not in dump
    assert provider_events(config.cache_db_path) == []


async def test_malformed_duplicate_increments_counter_like_ingest(tmp_path):
    config = provider_config(tmp_path)
    leading = json_bytes(
        stripe_event("evt_malformed_duplicate", customer="cus_unknown")
    )
    malformed = leading + b"\ntrailing-invalid"

    async with api_client(config) as client:
        first = await client.post(
            "/v1/webhooks/stripe",
            content=malformed,
            headers=signed_headers("stripe", malformed),
        )
        second = await client.post(
            "/v1/webhooks/stripe",
            content=malformed,
            headers=signed_headers("stripe", malformed),
        )

    row = provider_events(config.cache_db_path)[0]
    attempts = provider_attempts(config.cache_db_path)
    assert first.status_code == 400
    assert second.status_code == 400
    assert row["duplicate_count"] == 1
    assert [attempt["outcome"] for attempt in attempts] == [
        "malformed",
        "duplicate",
    ]


async def test_signed_malformed_json_is_durably_quarantined_only_when_safe(tmp_path):
    config = provider_config(tmp_path)
    leading = json_bytes(stripe_event("evt_malformed", customer="cus_unknown"))
    salvageable = leading + b"\ntrailing-invalid"
    truncated = leading[:-7]
    duplicate_keys = (
        b'{"id":"evt_first","id":"evt_second","type":"x","created":1}'
    )

    async with api_client(config) as client:
        safe = await client.post(
            "/v1/webhooks/stripe",
            content=salvageable,
            headers=signed_headers("stripe", salvageable),
        )
        unsafe = await client.post(
            "/v1/webhooks/stripe",
            content=truncated,
            headers=signed_headers("stripe", truncated),
        )
        duplicate = await client.post(
            "/v1/webhooks/stripe",
            content=duplicate_keys,
            headers=signed_headers("stripe", duplicate_keys),
        )

    assert safe.status_code == 400
    assert unsafe.status_code == 400
    assert duplicate.status_code == 400
    rows = provider_events(config.cache_db_path)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "evt_malformed"
    assert rows[0]["reason_code"] == "malformed_json"
    assert rows[0]["workspace_id"] is None


@pytest.mark.parametrize(
    "provider,event",
    [
        ("stripe", {"id": "evt_missing_type", "created": 1}),
        ("stripe", {"id": "evt_bad_created", "type": "x", "created": True}),
        ("stripe", {"id": "", "type": "x", "created": 1}),
        ("skool", {"id": "sk_missing_member", "type": "member.added", "created": 1}),
        ("skool", {"id": "sk_bad_type", "type": "official.skool.magic", "created": 1}),
        ("stripe", {"id": "evt_huge_time", "type": "x", "created": 10**1000}),
        ("skool", {"id": "sk_huge_time", "type": "member.added", "created": 10**1000}),
    ],
)
async def test_signed_invalid_envelopes_quarantine_or_reject_without_500(
    tmp_path,
    provider,
    event,
):
    config = provider_config(tmp_path)
    before = projection(config.cache_db_path)

    response = await _post(config, provider, event)

    assert response.status_code in {202, 400}
    assert response.status_code != 500
    assert projection(config.cache_db_path) == before
