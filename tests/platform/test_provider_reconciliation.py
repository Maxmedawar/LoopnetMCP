"""Reason-coded, audited, scoped provider reconciliation routes."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from urllib.parse import urlencode

import pytest

from cre_mcp.access.profiles import Profile
from cre_mcp.platform.providers import reconciliation as reconciliation_module
from cre_mcp.platform.providers.core import ProviderSyncService
from cre_mcp.platform.providers.reconciliation import (
    ProviderReconciliationStore,
)

from .admin_helpers import (
    VALID_REASON,
    api_client,
    audit_rows,
    provision_identity,
)
from .provider_helpers import (
    NOW,
    json_bytes,
    projection,
    provider_config,
    provider_events,
    seed_workspace,
    signed_headers,
    stripe_event,
)


def _reason_headers(headers, **values) -> dict[str, str]:
    reason = dict(VALID_REASON)
    reason.update(values)
    return {
        **headers,
        "x-admin-reason-code": reason["reason_code"],
        "x-admin-reason": reason["reason"],
    }


def _query(**values) -> str:
    return urlencode(values)


def _subject_user_id(path, workspace_id: int) -> int:
    with sqlite3.connect(path) as connection:
        return int(
            connection.execute(
                """
                SELECT user_id FROM platform_memberships
                WHERE workspace_id=? ORDER BY id LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()[0]
        )


async def _quarantine(config, event_id: str, customer: str):
    event = stripe_event(event_id, customer=customer)
    body = json_bytes(event)
    async with api_client(config) as client:
        response = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )
    assert response.status_code == 202
    return provider_events(config.cache_db_path)[-1]


async def test_reconciliation_routes_require_authoritative_admin(tmp_path):
    config = provider_config(tmp_path)
    ordinary = await provision_identity(config, "Ordinary", scopes=("admin:controls",))
    support = await provision_identity(
        config,
        "Support",
        internal_role="support",
    )
    row = await _quarantine(config, "evt_auth_queue", "cus_auth_queue")
    queue_path = "/v1/admin/provider-events/quarantine?provider=stripe"

    async with api_client(config) as client:
        missing = await client.get(queue_path)
        tenant = await client.get(queue_path, headers=ordinary.headers)
        readable = await client.get(
            queue_path,
            headers=_reason_headers(support.headers),
        )
        replay = await client.post(
            f"/v1/admin/provider-events/{row['id']}/replay",
            headers=support.headers,
            json=VALID_REASON,
        )

    assert missing.status_code == 401
    assert tenant.status_code == 403
    assert readable.status_code == 200
    assert replay.status_code == 403


@pytest.mark.parametrize(
    "query",
    [
        "",
        "provider=unknown",
        "provider=",
        "provider=stripe&limit=0",
        "provider=stripe&limit=1001",
        "provider=stripe&cursor=not-opaque",
    ],
)
async def test_quarantine_queue_rejects_unfiltered_or_invalid_paging(
    tmp_path,
    query,
):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Queue Validation",
        internal_role="platform_admin",
    )
    path = f"/v1/admin/provider-events/quarantine?{query}"

    async with api_client(config) as client:
        response = await client.get(
            path,
            headers=_reason_headers(admin.headers),
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "reason_values",
    [
        {"reason_code": "", "reason": "why"},
        {"reason_code": "not_allowed", "reason": "why"},
        {"reason_code": "support_resolution", "reason": ""},
    ],
)
async def test_reconciliation_requires_valid_reason_and_does_not_audit_failure(
    tmp_path,
    reason_values,
):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Reason Validation",
        internal_role="platform_admin",
    )
    path = urlencode({"provider": "stripe"})

    async with api_client(config) as client:
        response = await client.get(
            f"/v1/admin/provider-events/quarantine?{path}",
            headers=_reason_headers(admin.headers, **reason_values),
        )

    assert response.status_code == 422
    assert audit_rows(config.cache_db_path) == []


async def test_queue_is_provider_filtered_cursor_paged_and_payload_free(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Queue Paging",
        internal_role="platform_admin",
    )
    for index in range(3):
        await _quarantine(config, f"evt_page_{index}", f"cus_page_{index}")

    base = "/v1/admin/provider-events/quarantine?" + _query(
        provider="stripe",
        limit="2",
    )
    async with api_client(config) as client:
        reason_headers = _reason_headers(admin.headers)
        first = await client.get(base, headers=reason_headers)
        cursor = first.json()["next_cursor"]
        second = await client.get(
            base + "&cursor=" + cursor,
            headers=reason_headers,
        )

    first_ids = [item["id"] for item in first.json()["events"]]
    second_ids = [item["id"] for item in second.json()["events"]]
    serialized = first.text + second.text
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert set(first_ids).isdisjoint(second_ids)
    assert cursor and "evt_page" not in cursor
    for forbidden in (
        "normalized_data",
        "payload",
        "cus_page",
        "external_customer_id",
        "member_id",
    ):
        assert forbidden not in serialized
    actions = [row["action"] for row in audit_rows(config.cache_db_path)]
    assert actions == [
        "provider_event.quarantine_list",
        "provider_event.quarantine_list",
    ]


async def test_workspace_event_list_is_scoped_and_audited(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Workspace List Admin",
        internal_role="platform_admin",
    )
    first = await seed_workspace(
        config,
        "First Target",
        stripe_customer="cus_first_target",
    )
    second = await seed_workspace(
        config,
        "Second Target",
        stripe_customer="cus_second_target",
    )
    for event_id, customer in (
        ("evt_first_target", "cus_first_target"),
        ("evt_second_target", "cus_second_target"),
    ):
        event = stripe_event(
            event_id,
            customer=customer,
            object_id=f"sub_{event_id}",
        )
        body = json_bytes(event)
        async with api_client(config) as client:
            assert (
                await client.post(
                    "/v1/webhooks/stripe",
                    content=body,
                    headers=signed_headers("stripe", body),
                )
            ).status_code == 200

    async with api_client(config) as client:
        response = await client.get(
            f"/v1/admin/workspaces/{first.public_id}/provider-events?"
            + _query(limit="10"),
            headers=_reason_headers(admin.headers),
        )

    assert response.status_code == 200
    assert [item["event_type"] for item in response.json()["events"]] == [
        "customer.subscription.updated"
    ]
    ids = [item["id"] for item in response.json()["events"]]
    with sqlite3.connect(config.cache_db_path) as connection:
        expected = connection.execute(
            "SELECT id FROM platform_provider_events WHERE workspace_id=?",
            (first.id,),
        ).fetchall()
    assert ids == [row[0] for row in expected]
    assert second.public_id not in response.text
    assert audit_rows(config.cache_db_path)[0]["action"] == (
        "provider_event.workspace_list"
    )


@pytest.mark.parametrize("listing", ["quarantine", "workspace"])
async def test_audited_provider_lists_serialize_with_concurrent_wal_writer(
    tmp_path,
    monkeypatch,
    listing,
):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        f"Concurrent {listing} List Admin",
        internal_role="platform_admin",
    )
    if listing == "quarantine":
        await _quarantine(
            config,
            "evt_concurrent_queue_list",
            "cus_concurrent_queue_list",
        )
        workspace = None
    else:
        workspace = await seed_workspace(
            config,
            "Concurrent Workspace List",
            stripe_customer="cus_concurrent_workspace_list",
        )
        body = json_bytes(
            stripe_event(
                "evt_concurrent_workspace_list",
                customer="cus_concurrent_workspace_list",
            )
        )
        async with api_client(config) as client:
            assert (
                await client.post(
                    "/v1/webhooks/stripe",
                    content=body,
                    headers=signed_headers("stripe", body),
                )
            ).status_code == 200
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")

    store = ProviderReconciliationStore(
        config.cache_db_path,
        ProviderSyncService(config),
    )
    selected = threading.Event()
    writer_attempted = threading.Event()
    writer_acquired = threading.Event()
    release_writer = threading.Event()
    original_event = reconciliation_module._event

    def gated_event(row):
        selected.set()
        assert writer_attempted.wait(5)
        writer_acquired.wait(0.5)
        return original_event(row)

    monkeypatch.setattr(reconciliation_module, "_event", gated_event)

    def concurrent_writer():
        assert selected.wait(5)
        writer_attempted.set()
        with sqlite3.connect(config.cache_db_path, timeout=5) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
            writer_acquired.set()
            connection.execute(
                """
                UPDATE platform_provider_events
                SET updated_at=updated_at
                WHERE id=(SELECT MIN(id) FROM platform_provider_events)
                """
            )
            assert release_writer.wait(5)
            connection.commit()

    writer_task = asyncio.create_task(asyncio.to_thread(concurrent_writer))
    try:
        if listing == "quarantine":
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    store.quarantine_queue,
                    actor_user_id=admin.user_id,
                    provider="stripe",
                    limit=10,
                    cursor=None,
                    reason_code=VALID_REASON["reason_code"],
                    reason=VALID_REASON["reason"],
                ),
                timeout=5,
            )
        else:
            assert workspace is not None
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    store.workspace_events,
                    actor_user_id=admin.user_id,
                    workspace_public_id=workspace.public_id,
                    provider="stripe",
                    limit=10,
                    cursor=None,
                    reason_code=VALID_REASON["reason_code"],
                    reason=VALID_REASON["reason"],
                ),
                timeout=5,
            )
    finally:
        release_writer.set()
        await writer_task

    assert len(result["events"]) == 1


async def test_admin_replay_re_resolves_mapping_and_is_idempotent(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Replay Admin",
        internal_role="platform_admin",
    )
    target = await seed_workspace(config, "Replay Target")
    row = await _quarantine(config, "evt_replay", "cus_replay")
    now = NOW.isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                target.id,
                _subject_user_id(config.cache_db_path, target.id),
                "stripe",
                "cus_replay",
                "{}",
                now,
                now,
            ),
        )
    route = f"/v1/admin/provider-events/{row['id']}/replay"

    async with api_client(config) as client:
        first = await client.post(
            route,
            headers=admin.headers,
            json=VALID_REASON,
        )
        after_first = projection(config.cache_db_path)
        second = await client.post(
            route,
            headers=admin.headers,
            json=VALID_REASON,
        )

    assert first.status_code == 200
    assert first.json()["event"]["outcome"] == "reconciled"
    assert second.status_code == 200
    assert second.json()["outcome"] == "reconciled"
    assert projection(config.cache_db_path) == after_first
    assert EntitlementStore(config.cache_db_path).effective_access(
        target.id,
        subject_user_id=_subject_user_id(
            config.cache_db_path,
            target.id,
        ),
    ) is not None
    assert [row["action"] for row in audit_rows(config.cache_db_path)] == [
        "provider_event.replay",
        "provider_event.replay",
    ]


async def test_replaying_non_quarantined_event_is_fixed_conflict(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Replay Conflict",
        internal_role="platform_admin",
    )
    await seed_workspace(config, "Applied Target", stripe_customer="cus_applied")
    event = stripe_event("evt_applied", customer="cus_applied")
    body = json_bytes(event)
    async with api_client(config) as client:
        assert (
            await client.post(
                "/v1/webhooks/stripe",
                content=body,
                headers=signed_headers("stripe", body),
            )
        ).status_code == 200
    row = provider_events(config.cache_db_path)[0]

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/provider-events/{row['id']}/replay",
            headers=admin.headers,
            json=VALID_REASON,
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "evt_applied" not in response.text


async def test_historical_jv_identity_is_denied_reconciliation(tmp_path):
    config = provider_config(tmp_path)
    identity = await provision_identity(
        config,
        "JV Internal Denied",
        internal_role="platform_admin",
        profile=Profile.JV_PARTNER,
    )
    path = "/v1/admin/provider-events/quarantine?" + _query(provider="stripe")

    async with api_client(config) as client:
        response = await client.get(
            path,
            headers=_reason_headers(identity.headers),
        )

    assert response.status_code == 403


async def test_replay_audit_failure_rolls_back_projection_and_event(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Replay Rollback",
        internal_role="platform_admin",
    )
    target = await seed_workspace(config, "Rollback Target")
    row = await _quarantine(config, "evt_replay_rollback", "cus_replay_rollback")
    now = NOW.isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                target.id,
                _subject_user_id(config.cache_db_path, target.id),
                "stripe",
                "cus_replay_rollback",
                "{}",
                now,
                now,
            ),
        )
        connection.execute(
            """
            CREATE TRIGGER reject_provider_replay_audit
            BEFORE INSERT ON platform_admin_audit
            WHEN NEW.action='provider_event.replay'
            BEGIN
                SELECT RAISE(ABORT, 'injected replay audit failure');
            END
            """
        )
    before = projection(config.cache_db_path)

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/provider-events/{row['id']}/replay",
            headers=admin.headers,
            json=VALID_REASON,
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "admin_audit_failed"
    assert projection(config.cache_db_path) == before
    assert provider_events(config.cache_db_path)[0]["outcome"] == "quarantined"


async def test_requarantine_during_replay_stamps_replayed_at(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "Requarantine Replay Admin",
        internal_role="platform_admin",
    )
    row = await _quarantine(
        config,
        "evt_requarantine_replay",
        "cus_still_unmapped",
    )

    async with api_client(config) as client:
        response = await client.post(
            f"/v1/admin/provider-events/{row['id']}/replay",
            headers=admin.headers,
            json=VALID_REASON,
        )

    stored = provider_events(config.cache_db_path)[0]
    assert response.status_code == 200
    assert response.json()["outcome"] == "quarantined"
    assert stored["outcome"] == "quarantined"
    assert stored["reason_code"] == "unmapped_external_account"
    assert stored["replayed_at"] is not None


async def test_no_provider_state_replay_is_idempotently_rejected(tmp_path):
    config = provider_config(tmp_path)
    admin = await provision_identity(
        config,
        "No State Replay Admin",
        internal_role="platform_admin",
    )
    target = await seed_workspace(config, "No State Replay Target")
    event = stripe_event(
        "evt_no_state_replay",
        event_type="customer.subscription.deleted",
        customer="cus_no_state_replay",
        status="canceled",
    )
    body = json_bytes(event)
    async with api_client(config) as client:
        quarantined = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )
    assert quarantined.status_code == 202
    row = provider_events(config.cache_db_path)[0]
    now = NOW.isoformat()
    with sqlite3.connect(config.cache_db_path) as connection:
        connection.execute(
            """
            INSERT INTO platform_external_accounts(
                workspace_id,subject_user_id,provider,external_account_id,
                metadata,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                target.id,
                _subject_user_id(config.cache_db_path, target.id),
                "stripe",
                "cus_no_state_replay",
                "{}",
                now,
                now,
            ),
        )
    route = f"/v1/admin/provider-events/{row['id']}/replay"

    async with api_client(config) as client:
        first = await client.post(
            route,
            headers=admin.headers,
            json=VALID_REASON,
        )
        after_first = projection(config.cache_db_path)
        second = await client.post(
            route,
            headers=admin.headers,
            json=VALID_REASON,
        )

    assert first.status_code == 200
    assert first.json()["outcome"] == "rejected"
    assert first.json()["reason_code"] == "no_provider_state"
    assert second.status_code == 200
    assert second.json()["outcome"] == "rejected"
    assert second.json()["reason_code"] == "no_provider_state"
    assert projection(config.cache_db_path) == after_first
    stored = provider_events(config.cache_db_path)[0]
    assert stored["replayed_at"] is not None


# Imported late to keep helper setup compact and make the entitlement assertion
# explicit at the route contract.
from cre_mcp.platform.entitlements import EntitlementStore
