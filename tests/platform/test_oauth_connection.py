"""Connection-only Clerk session and OAuth 2.1 HTTP flow."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from urllib.parse import parse_qs, urlsplit

import httpx

from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import starlette_app
from cre_mcp.platform.authority import AuthorityResolver
from cre_mcp.platform.connection import FakeHumanIdentityVerifier, VerifiedHumanIdentity
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.server import create_http_app

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "a" * 64
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode("ascii")).digest()
).rstrip(b"=").decode("ascii")


def _config(tmp_path) -> CreConfig:
    return CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        transport="http",
        human_identity_provider="clerk",
        oauth_issuer="https://mcp.example.test",
        oauth_resource="https://mcp.example.test/mcp",
        connection_url="https://connect.example.test/connect",
        browser_cookie_secure=True,
    )


async def _provision(config: CreConfig):
    repository = PlatformRepository(config)
    workspace = await repository.create_workspace("Buyer Workspace")
    user = await repository.create_user("buyer@example.test", "Buyer")
    assert workspace is not None and user is not None
    membership = await repository.add_membership(workspace.public_id, user.id, "owner")
    assert membership is not None
    return workspace, user


async def test_discovery_dynamic_registration_and_full_pkce_connection(tmp_path):
    config = _config(tmp_path)
    workspace, user = await _provision(config)
    identity = VerifiedHumanIdentity(
        "clerk", "user_clerk_1", user.email, user.name
    )
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({"clerk-token": identity}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
        follow_redirects=False,
    ) as client:
        metadata = await client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200
        assert metadata.json()["code_challenge_methods_supported"] == ["S256"]
        protected = await client.get("/.well-known/oauth-protected-resource")
        assert protected.json()["resource"] == config.oauth_resource

        registration = await client.post(
            "/oauth/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [REDIRECT],
                "scope": "mcp:tools",
            },
        )
        assert registration.status_code == 201
        client_id = registration.json()["client_id"]
        assert "workspace_id" not in registration.json()

        authorize = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": "mcp:tools",
                "state": "opaque-client-state",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "resource": config.oauth_resource,
            },
        )
        assert authorize.status_code == 303
        pending = parse_qs(urlsplit(authorize.headers["location"]).query)["request"][0]

        browser = await client.post(
            "/v1/browser/session",
            headers={"authorization": "Bearer clerk-token"},
        )
        assert browser.status_code == 201
        assert browser.json()["user"] == {
            "id": user.id,
            "email": user.email,
            "name": user.name,
        }
        assert browser.json()["connection"]["workspace_id"] == workspace.public_id
        assert "csrf_token" in browser.json()
        assert "mcr_browser=" in browser.headers["set-cookie"]
        assert "HttpOnly" in browser.headers["set-cookie"]
        assert "Secure" in browser.headers["set-cookie"]
        assert "SameSite=lax" in browser.headers["set-cookie"]

        complete = await client.get("/oauth/authorize", params={"request": pending})
        assert complete.status_code == 303
        callback = parse_qs(urlsplit(complete.headers["location"]).query)
        assert callback["state"] == ["opaque-client-state"]
        code = callback["code"][0]

        token = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code": code,
                "code_verifier": VERIFIER,
            },
        )
        assert token.status_code == 200
        payload = token.json()
        assert payload["token_type"] == "Bearer"
        assert payload["scope"] == "mcp:tools"
        assert payload["access_token"].startswith("mcr_at_")
        assert payload["refresh_token"].startswith("mcr_rt_")


async def test_authorize_rejects_all_client_supplied_authority_selectors(tmp_path):
    config = _config(tmp_path)
    await _provision(config)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.test"
    ) as client:
        registration = await client.post(
            "/oauth/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [REDIRECT],
                "scope": "mcp:tools",
            },
        )
        client_id = registration.json()["client_id"]
        for selector in ("workspace_id", "user_id", "profile", "plan", "territory"):
            response = await client.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": REDIRECT,
                    "scope": "mcp:tools",
                    "state": "state",
                    "code_challenge": CHALLENGE,
                    "code_challenge_method": "S256",
                    "resource": config.oauth_resource,
                    selector: "invented",
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "authority_selector_forbidden"


async def test_authorize_rejects_oversized_state(tmp_path):
    config = _config(tmp_path)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.test"
    ) as client:
        registration = await client.post(
            "/oauth/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [REDIRECT],
                "scope": "mcp:tools",
            },
        )
        response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registration.json()["client_id"],
                "redirect_uri": REDIRECT,
                "scope": "mcp:tools",
                "state": "s" * 513,
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "resource": config.oauth_resource,
            },
        )

    assert response.status_code == 400
    assert "512" in response.json()["error"]["message"]


async def test_connection_fails_closed_without_configured_clerk(tmp_path):
    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "platform.db",
        human_identity_provider="disabled",
    )
    app = starlette_app(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.test"
    ) as client:
        response = await client.post(
            "/v1/browser/session", headers={"authorization": "Bearer anything"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "human_identity_unconfigured"


async def test_browser_session_cors_is_exact_origin_and_credentials_safe(tmp_path):
    config = _config(tmp_path)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.test"
    ) as client:
        allowed = await client.options(
            "/v1/browser/session",
            headers={
                "origin": "https://connect.example.test",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization",
            },
        )
        denied = await client.options(
            "/v1/browser/session",
            headers={
                "origin": "https://attacker.example",
                "access-control-request-method": "POST",
            },
        )

    assert allowed.status_code == 204
    assert allowed.headers["access-control-allow-origin"] == "https://connect.example.test"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert allowed.headers["vary"] == "Origin"
    assert denied.status_code == 403


async def test_ambiguous_workspace_membership_does_not_issue_code(tmp_path):
    config = _config(tmp_path)
    _, user = await _provision(config)
    repository = PlatformRepository(config)
    second = await repository.create_workspace("Second Workspace")
    assert second is not None
    assert await repository.add_membership(second.public_id, user.id, "owner") is not None
    identity = VerifiedHumanIdentity("clerk", "subject", user.email, user.name)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({"token": identity}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
        follow_redirects=False,
    ) as client:
        registration = await client.post(
            "/oauth/register",
            json={"client_name": "Claude", "redirect_uris": [REDIRECT], "scope": "mcp:tools"},
        )
        client_id = registration.json()["client_id"]
        start = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "scope": "mcp:tools",
                "state": "state",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "resource": config.oauth_resource,
            },
        )
        pending = parse_qs(urlsplit(start.headers["location"]).query)["request"][0]
        assert (
            await client.post(
                "/v1/browser/session", headers={"authorization": "Bearer token"}
            )
        ).status_code == 201
        complete = await client.get("/oauth/authorize", params={"request": pending})
    assert complete.status_code == 409
    assert complete.json()["error"]["code"] == "workspace_selection_required"


async def test_suspended_account_does_not_issue_code(tmp_path):
    config = _config(tmp_path)
    workspace, user = await _provision(config)
    entitlements = EntitlementStore(config.cache_db_path)
    entitlements.set_account_state(workspace.public_id, "suspended", reason="manual hold")
    identity = VerifiedHumanIdentity("clerk", "subject", user.email, user.name)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({"token": identity}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
        follow_redirects=False,
    ) as client:
        registration = await client.post(
            "/oauth/register",
            json={"client_name": "Claude", "redirect_uris": [REDIRECT], "scope": "mcp:tools"},
        )
        start = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registration.json()["client_id"],
                "redirect_uri": REDIRECT,
                "scope": "mcp:tools",
                "state": "state",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "resource": config.oauth_resource,
            },
        )
        pending = parse_qs(urlsplit(start.headers["location"]).query)["request"][0]
        browser = await client.post(
            "/v1/browser/session", headers={"authorization": "Bearer token"}
        )
        complete = await client.get("/oauth/authorize", params={"request": pending})

    assert browser.status_code == 201
    assert browser.json()["connection"]["status"] == "access_blocked"
    assert complete.status_code == 403
    assert complete.json()["error"]["code"] == "account_access_blocked"


async def test_removed_membership_and_revoked_browser_session_fail_closed(tmp_path):
    config = _config(tmp_path)
    workspace, user = await _provision(config)
    identity = VerifiedHumanIdentity("clerk", "subject", user.email, user.name)
    app = starlette_app(
        config,
        human_identity_verifier=FakeHumanIdentityVerifier({"token": identity}),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://mcp.example.test",
        follow_redirects=False,
    ) as client:
        registration = await client.post(
            "/oauth/register",
            json={"client_name": "Claude", "redirect_uris": [REDIRECT], "scope": "mcp:tools"},
        )
        start = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registration.json()["client_id"],
                "redirect_uri": REDIRECT,
                "scope": "mcp:tools",
                "state": "state",
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
            },
        )
        pending = parse_qs(urlsplit(start.headers["location"]).query)["request"][0]
        browser = await client.post(
            "/v1/browser/session", headers={"authorization": "Bearer token"}
        )
        csrf = browser.json()["csrf_token"]

        with sqlite3.connect(config.cache_db_path) as connection:
            connection.execute(
                "DELETE FROM platform_memberships WHERE workspace_id=(SELECT id FROM platform_workspaces WHERE public_id=?) AND user_id=?",
                (workspace.public_id, user.id),
            )
        no_membership = await client.get("/oauth/authorize", params={"request": pending})
        logout = await client.request(
            "DELETE", "/v1/browser/session", headers={"x-csrf-token": csrf}
        )
        after_logout = await client.get("/oauth/authorize", params={"request": pending})

    assert no_membership.status_code == 409
    assert logout.status_code == 200
    assert after_logout.status_code == 303
    assert after_logout.headers["location"].startswith(config.connection_url)


async def test_oauth_discovery_and_registration_ride_real_hosted_mcp_app(tmp_path):
    config = _config(tmp_path)
    app = create_http_app(config=config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.example.test"
    ) as client:
        metadata = await client.get("/.well-known/oauth-authorization-server")
        registration = await client.post(
            "/oauth/register",
            json={
                "client_name": "Claude",
                "redirect_uris": [REDIRECT],
                "scope": "mcp:tools",
            },
        )

    assert metadata.status_code == 200
    assert registration.status_code == 201
    assert registration.json()["client_id"].startswith("mcr_client_")


async def test_clerk_connection_token_initializes_and_calls_real_hosted_mcp(tmp_path):
    config = _config(tmp_path)
    workspace, user = await _provision(config)
    plan = await PlatformRepository(config).create_plan(
        "operator",
        "Full Operator",
        daily_quotas={},
    )
    assert plan is not None
    EntitlementStore(config.cache_db_path).grant_access(
        workspace=workspace.public_id,
        source="manual",
        external_ref="connection-e2e",
        profile=Profile.FULL_OPERATOR,
        plan_key="operator",
        subject_user_id=user.id,
        scope="subject",
    )
    identity = VerifiedHumanIdentity("clerk", "subject", user.email, user.name)
    app = create_http_app(
        config=config,
        human_identity_verifier=FakeHumanIdentityVerifier({"token": identity}),
    )
    common_headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://mcp.example.test",
            follow_redirects=False,
        ) as client:
            registration = await client.post(
                "/oauth/register",
                json={
                    "client_name": "Claude",
                    "redirect_uris": [REDIRECT],
                    "scope": "mcp:tools",
                },
            )
            start = await client.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": registration.json()["client_id"],
                    "redirect_uri": REDIRECT,
                    "scope": "mcp:tools",
                    "state": "state",
                    "code_challenge": CHALLENGE,
                    "code_challenge_method": "S256",
                },
            )
            pending = parse_qs(urlsplit(start.headers["location"]).query)["request"][0]
            assert (
                await client.post(
                    "/v1/browser/session",
                    headers={"authorization": "Bearer token"},
                )
            ).status_code == 201
            completed = await client.get(
                "/oauth/authorize", params={"request": pending}
            )
            code = parse_qs(urlsplit(completed.headers["location"]).query)["code"][0]
            exchanged = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": registration.json()["client_id"],
                    "redirect_uri": REDIRECT,
                    "code": code,
                    "code_verifier": VERIFIER,
                },
            )
            access_token = exchanged.json()["access_token"]
            authority = AuthorityResolver(
                config.cache_db_path,
                audience=config.oauth_audience,
                resource=config.oauth_resource,
            ).resolve(access_token)
            assert authority is not None and authority.access_allowed, authority
            headers = {
                **common_headers,
                "authorization": f"Bearer {access_token}",
            }
            initialized = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "connection-test", "version": "1"},
                    },
                },
            )
            session_id = initialized.headers["mcp-session-id"]
            session_headers = {**headers, "mcp-session-id": session_id}
            assert (
                await client.post(
                    "/mcp",
                    headers=session_headers,
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    },
                )
            ).status_code == 202
            called = await client.post(
                "/mcp",
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "cre_pipeline",
                        "arguments": {"action": "list_searches", "arguments": {}},
                    },
                },
            )

    assert initialized.status_code == 200
    assert called.status_code == 200
    assert called.json()["result"]["isError"] is False
    assert called.json()["result"]["structuredContent"]["searches"] == []
