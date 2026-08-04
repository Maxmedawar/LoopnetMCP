"""Internal-only Operations Console browser authorization and BFF contract."""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx

from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import starlette_app
from cre_mcp.platform.connection import FakeHumanIdentityVerifier, VerifiedHumanIdentity
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

from .admin_helpers import _seed_internal_admin, audit_rows
from .provider_helpers import (
    STRIPE_SECRET,
    json_bytes,
    provider_events,
    signed_headers,
    stripe_event,
)


ORIGIN = "https://operations.example.test"
HOST = "platform.example.test"


def _config(tmp_path, *, enabled: bool = True) -> CreConfig:
    return CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        oauth_issuer=f"https://{HOST}",
        operations_console_origin=ORIGIN if enabled else None,
        browser_cookie_secure=True,
        stripe_webhook_secret=STRIPE_SECRET,
    )


async def _person(
    config: CreConfig,
    name: str,
    *,
    internal_role: str | None = None,
    internal_active: bool = True,
    profile: Profile | None = None,
):
    repository = PlatformRepository(config)
    workspace = await repository.create_workspace(f"{name} Workspace")
    user = await repository.create_user(
        f"{name.casefold().replace(' ', '-')}@example.test",
        name,
    )
    assert workspace is not None and user is not None
    membership = await repository.add_membership(workspace.public_id, user.id, "owner")
    assert membership is not None
    if internal_role is not None:
        _seed_internal_admin(
            config.cache_db_path,
            user_id=user.id,
            role=internal_role,
            active=internal_active,
        )
    if profile is not None:
        EntitlementStore(config.cache_db_path).grant_access(
            workspace=workspace.public_id,
            source="jv" if profile is Profile.JV_PARTNER else "manual",
            external_ref=f"profile-{user.id}",
            profile=profile,
            plan_key="partner" if profile is Profile.JV_PARTNER else "pro",
            subject_user_id=None if profile is Profile.JV_PARTNER else user.id,
            scope="workspace" if profile is Profile.JV_PARTNER else "subject",
        )
    return workspace, user, membership


def _headers(**extra: str) -> dict[str, str]:
    return {"origin": ORIGIN, "host": HOST, **extra}


async def _client(
    config: CreConfig,
    identity: VerifiedHumanIdentity | None = None,
    *,
    stripe_reconciliation_service: Any = None,
):
    verifier = FakeHumanIdentityVerifier(
        {"clerk-operator-token": identity} if identity is not None else {}
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=starlette_app(
                config,
                human_identity_verifier=verifier,
                stripe_reconciliation_service=stripe_reconciliation_service,
            )
        ),
        base_url=f"https://{HOST}",
    )


async def _sign_in(client: httpx.AsyncClient):
    response = await client.post(
        "/v1/operations/session",
        headers=_headers(authorization="Bearer clerk-operator-token"),
    )
    return response, response.json().get("csrf_token")


async def test_console_is_disabled_without_internal_origin(tmp_path):
    config = _config(tmp_path, enabled=False)
    async with await _client(config) as client:
        response = await client.get("/v1/operations/health", headers=_headers())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "operations_disabled"


async def test_clerk_operator_session_is_opaque_cookie_and_live_role(tmp_path):
    config = _config(tmp_path)
    _workspace, user, _membership = await _person(
        config, "Platform Operator", internal_role="platform_admin"
    )
    identity = VerifiedHumanIdentity("clerk", "staff-subject", user.email, user.name)

    async with await _client(config, identity) as client:
        response, csrf = await _sign_in(client)
        current = await client.get("/v1/operations/session", headers=_headers())

    assert response.status_code == 201
    assert response.json()["operator"] == {
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": "platform_admin",
    }
    assert csrf.startswith("mcr_ops_csrf_")
    assert "clerk-operator-token" not in response.text
    assert "mcr_ops=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert current.status_code == 200
    assert current.json()["operator"]["role"] == "platform_admin"


async def test_console_rejects_wrong_origin_host_and_non_operator(tmp_path):
    config = _config(tmp_path)
    _workspace, user, _membership = await _person(config, "Ordinary Customer")
    identity = VerifiedHumanIdentity("clerk", "customer-subject", user.email, user.name)

    async with await _client(config, identity) as client:
        wrong_origin = await client.post(
            "/v1/operations/session",
            headers={
                "origin": "https://attacker.example",
                "host": HOST,
                "authorization": "Bearer clerk-operator-token",
            },
        )
        wrong_host = await client.post(
            "/v1/operations/session",
            headers={
                "origin": ORIGIN,
                "host": "attacker.example",
                "authorization": "Bearer clerk-operator-token",
            },
        )
        customer = await client.post(
            "/v1/operations/session",
            headers=_headers(authorization="Bearer clerk-operator-token"),
        )

    assert wrong_origin.status_code == 403
    assert wrong_host.status_code == 403
    assert customer.status_code == 403


async def test_support_reads_but_cannot_mutate_and_admin_needs_csrf(tmp_path):
    config = _config(tmp_path)
    target, _target_user, _target_membership = await _person(config, "Managed Buyer")
    _support_ws, support, _ = await _person(
        config, "Support Reader", internal_role="support"
    )
    support_identity = VerifiedHumanIdentity(
        "clerk", "support-subject", support.email, support.name
    )

    async with await _client(config, support_identity) as client:
        signed_in, csrf = await _sign_in(client)
        read = await client.get(
            f"/v1/operations/workspaces/{target.public_id}", headers=_headers()
        )
        write = await client.post(
            f"/v1/operations/workspaces/{target.public_id}/account-state",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "state": "suspended",
                "reason_code": "support_resolution",
                "reason": "Requested from the internal runbook.",
            },
        )

    assert signed_in.status_code == 201
    assert read.status_code == 200
    assert write.status_code == 403

    _admin_ws, admin, _ = await _person(
        config, "Control Admin", internal_role="platform_admin"
    )
    admin_identity = VerifiedHumanIdentity("clerk", "admin-subject", admin.email, admin.name)
    async with await _client(config, admin_identity) as client:
        _signed_in, csrf = await _sign_in(client)
        missing = await client.post(
            f"/v1/operations/workspaces/{target.public_id}/account-state",
            headers=_headers(),
            json={
                "state": "suspended",
                "reason_code": "support_resolution",
                "reason": "Requested from the internal runbook.",
            },
        )
        changed = await client.post(
            f"/v1/operations/workspaces/{target.public_id}/account-state",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "state": "suspended",
                "reason_code": "support_resolution",
                "reason": "Requested from the internal runbook.",
            },
        )

    assert missing.status_code == 403
    assert changed.status_code == 200
    assert changed.json()["account"]["state"] == "suspended"
    assert audit_rows(config.cache_db_path)[-1]["action"] == "account.state.update"


async def test_removed_admin_and_jv_operator_fail_closed(tmp_path):
    config = _config(tmp_path)
    _workspace, operator, _membership = await _person(
        config, "Removed Admin", internal_role="platform_admin"
    )
    identity = VerifiedHumanIdentity("clerk", "removed-subject", operator.email, operator.name)

    async with await _client(config, identity) as client:
        signed_in, _csrf = await _sign_in(client)
        with sqlite3.connect(config.cache_db_path) as connection:
            connection.execute(
                "UPDATE platform_internal_admins SET active=0 WHERE user_id=?",
                (operator.id,),
            )
        stale = await client.get("/v1/operations/health", headers=_headers())

    assert signed_in.status_code == 201
    assert stale.status_code == 403

    _jv_workspace, jv_admin, _ = await _person(
        config,
        "JV Admin",
        internal_role="platform_admin",
        profile=Profile.JV_PARTNER,
    )
    jv_identity = VerifiedHumanIdentity("clerk", "jv-subject", jv_admin.email, jv_admin.name)
    async with await _client(config, jv_identity) as client:
        denied, _csrf = await _sign_in(client)

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "operator_separation_required"


async def test_workspace_search_is_bounded_and_source_rights_are_internal(tmp_path):
    config = _config(tmp_path)
    _workspace, operator, _ = await _person(
        config, "Lookup Admin", internal_role="platform_admin"
    )
    target, _target_user, _target_membership = await _person(config, "Austin Buyer")
    identity = VerifiedHumanIdentity("clerk", "lookup-subject", operator.email, operator.name)

    async with await _client(config, identity) as client:
        await _sign_in(client)
        found = await client.get(
            "/v1/operations/workspaces",
            headers=_headers(),
            params={"q": target.public_id, "limit": "10"},
        )
        over_limit = await client.get(
            "/v1/operations/workspaces",
            headers=_headers(),
            params={"q": "Austin", "limit": "51"},
        )
        rights = await client.get("/v1/operations/source-rights", headers=_headers())

    assert found.status_code == 200
    assert found.json()["workspaces"][0]["public_id"] == target.public_id
    assert over_limit.status_code == 422
    assert rights.status_code == 200
    assert rights.json()["summary"]["total"] > 0
    assert any(
        item["source_id"] == "listing.loopnet"
        and item["hosted_cloud_allowed"] is False
        for item in rights.json()["sources"]
    )


async def test_operations_preflight_is_exact_and_session_logout_needs_csrf(tmp_path):
    config = _config(tmp_path)
    _workspace, operator, _ = await _person(
        config, "Logout Admin", internal_role="platform_admin"
    )
    identity = VerifiedHumanIdentity("clerk", "logout-subject", operator.email, operator.name)

    async with await _client(config, identity) as client:
        preflight = await client.options(
            "/v1/operations/session",
            headers=_headers(
                **{
                    "access-control-request-method": "POST",
                    "access-control-request-headers": "authorization, content-type",
                }
            ),
        )
        _signed_in, csrf = await _sign_in(client)
        missing = await client.delete("/v1/operations/session", headers=_headers())
        logout = await client.delete(
            "/v1/operations/session",
            headers=_headers(**{"x-csrf-token": csrf}),
        )
        after = await client.get("/v1/operations/session", headers=_headers())

    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == ORIGIN
    assert preflight.headers["access-control-allow-credentials"] == "true"
    assert missing.status_code == 403
    assert logout.status_code == 200
    assert after.status_code == 401


async def test_operator_mutations_require_reason_are_audited_and_path_scoped(tmp_path):
    config = _config(tmp_path)
    first, _first_user, _ = await _person(config, "First Customer")
    second, _second_user, _ = await _person(config, "Second Customer")
    _operator_workspace, operator, _ = await _person(
        config, "Mutation Admin", internal_role="platform_admin"
    )
    identity = VerifiedHumanIdentity(
        "clerk", "mutation-subject", operator.email, operator.name
    )

    async with await _client(config, identity) as client:
        _signed_in, csrf = await _sign_in(client)
        missing_reason = await client.post(
            f"/v1/operations/workspaces/{first.public_id}/territories",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={"name": "Austin", "state": "TX"},
        )
        created = await client.post(
            f"/v1/operations/workspaces/{first.public_id}/territories",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "name": "Austin",
                "state": "TX",
                "reason_code": "customer_request",
                "reason": "Customer requested Austin territory coverage.",
            },
        )
        territory_id = created.json()["territory"]["id"]
        wrong_workspace = await client.request(
            "DELETE",
            f"/v1/operations/workspaces/{second.public_id}/territories/{territory_id}",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "reason_code": "customer_request",
                "reason": "Attempted cross-workspace removal must fail closed.",
            },
        )
        audit = await client.get(
            "/v1/operations/audit",
            headers=_headers(),
            params={"workspace_id": first.public_id},
        )

    assert missing_reason.status_code == 422
    assert created.status_code == 201
    assert wrong_workspace.status_code == 404
    assert [row["action"] for row in audit_rows(config.cache_db_path)] == [
        "territory.create"
    ]
    assert audit.status_code == 200
    event = audit.json()["events"][0]
    assert event["actor_email"] == operator.email
    assert event["target_id"] == str(territory_id)
    assert event["before"] is None
    assert event["after"]["name"] == "Austin"


async def test_provider_quarantine_is_internal_and_replay_is_reason_gated(tmp_path):
    config = _config(tmp_path)
    _workspace, operator, _ = await _person(
        config, "Provider Admin", internal_role="platform_admin"
    )
    identity = VerifiedHumanIdentity(
        "clerk", "provider-subject", operator.email, operator.name
    )
    value = stripe_event("evt_console_quarantine", customer="cus_unmapped_console")
    body = json_bytes(value)

    async with await _client(config, identity) as client:
        ingested = await client.post(
            "/v1/webhooks/stripe",
            content=body,
            headers=signed_headers("stripe", body),
        )
        _signed_in, csrf = await _sign_in(client)
        queue = await client.get(
            "/v1/operations/provider-events/quarantine",
            headers=_headers(),
            params={"provider": "stripe"},
        )
        event_id = provider_events(config.cache_db_path)[-1]["id"]
        missing_reason = await client.post(
            f"/v1/operations/provider-events/{event_id}/replay",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={},
        )
        replay = await client.post(
            f"/v1/operations/provider-events/{event_id}/replay",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "reason_code": "support_resolution",
                "reason": "Replayed after confirming provider mapping remained absent.",
            },
        )

    assert ingested.status_code == 202
    assert queue.status_code == 200
    assert queue.json()["events"][0]["id"] == event_id
    assert "event_id" not in queue.json()["events"][0]
    assert missing_reason.status_code == 422
    assert replay.status_code == 200
    assert [row["action"] for row in audit_rows(config.cache_db_path)][-2:] == [
        "provider_event.quarantine_list",
        "provider_event.replay",
    ]


async def test_stripe_reconciliation_route_is_admin_csrf_and_reason_gated(tmp_path):
    config = _config(tmp_path)
    target, _target_user, _ = await _person(config, "Stripe Target")
    _workspace, operator, _ = await _person(
        config,
        "Stripe Operator",
        internal_role="platform_admin",
    )
    identity = VerifiedHumanIdentity(
        "clerk",
        "stripe-operator-subject",
        operator.email,
        operator.name,
    )

    class FakeReconciliation:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def reconcile_workspace(self, workspace_id: str, **values: Any):
            self.calls.append({"workspace_id": workspace_id, **values})
            return {
                "provider": "stripe",
                "mode": "test",
                "complete": True,
                "observed_at": "2026-08-04T18:00:00+00:00",
                "discrepancy_count": 1,
                "results": [],
            }

    reconciliation = FakeReconciliation()
    async with await _client(
        config,
        identity,
        stripe_reconciliation_service=reconciliation,
    ) as client:
        _signed_in, csrf = await _sign_in(client)
        missing_csrf = await client.post(
            f"/v1/operations/workspaces/{target.public_id}/stripe-reconcile",
            headers=_headers(),
            json={
                "reason_code": "billing_correction",
                "reason": "Compared the complete Stripe test state.",
            },
        )
        reconciled = await client.post(
            f"/v1/operations/workspaces/{target.public_id}/stripe-reconcile",
            headers=_headers(**{"x-csrf-token": csrf}),
            json={
                "reason_code": "billing_correction",
                "reason": "Compared the complete Stripe test state.",
            },
        )

    assert missing_csrf.status_code == 403
    assert reconciled.status_code == 200
    assert reconciled.json()["discrepancy_count"] == 1
    assert reconciliation.calls == [
        {
            "workspace_id": target.public_id,
            "actor_user_id": operator.id,
            "reason_code": "billing_correction",
            "reason": "Compared the complete Stripe test state.",
        }
    ]
