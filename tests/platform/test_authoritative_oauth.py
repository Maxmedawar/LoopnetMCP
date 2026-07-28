"""Adversarial tests for authoritative OAuth across HTTP MCP and ``/v1``."""

from __future__ import annotations

import asyncio
import inspect
import socket
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from fastmcp import FastMCP

from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.config import CreConfig
from cre_mcp.platform.api import PlatformApi, starlette_app
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.server import create_http_app, install_access_control

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
MCP_SCOPE = "mcp:tools"
DEAL_SCOPES = ("deals:read", "deals:write")
ALL_SCOPES = (MCP_SCOPE, *DEAL_SCOPES)


class ProvisionedTenant:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_row_id: int,
        user_id: int,
        membership_id: int,
        client_id: str,
        token: str,
        grant_id: int | None,
        territory_id: int | None,
        plan_id: int | None,
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_row_id = workspace_row_id
        self.user_id = user_id
        self.membership_id = membership_id
        self.client_id = client_id
        self.token = token
        self.grant_id = grant_id
        self.territory_id = territory_id
        self.plan_id = plan_id

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


def _config(tmp_path) -> CreConfig:
    return CreConfig(
        _env_file=None,
        transport="http",
        cache_db_path=tmp_path / "platform.db",
        access_registry_path=tmp_path / "access" / "registry.json",
        access_audit_path=tmp_path / "access" / "audit.jsonl",
    )


async def _provision(
    config: CreConfig,
    name: str,
    *,
    profile: Profile = Profile.FULL_OPERATOR,
    scopes: tuple[str, ...] = ALL_SCOPES,
    grant: bool = True,
    territory_state: str | None = None,
    access_ttl: timedelta = timedelta(minutes=15),
    audience: str = "medawarcre-mcp",
    resource: str | None = None,
    plan_key: str = "pro",
    plan_quotas: dict[str, int] | None = None,
    provision_plan: bool = True,
) -> ProvisionedTenant:
    repository = PlatformRepository(config.cache_db_path)
    auth = OAuthSessionStore(config.cache_db_path)
    entitlements = EntitlementStore(config.cache_db_path)

    plan = None
    if provision_plan:
        plan = next(
            (
                item
                for item in await repository.list_plans()
                if item.key == plan_key
            ),
            None,
        )
        if plan is None:
            plan = await repository.create_plan(
                plan_key,
                plan_key.title(),
                daily_quotas=plan_quotas or {},
            )
        elif plan_quotas is not None:
            plan = await repository.update_plan(
                plan.id,
                daily_quotas=plan_quotas,
            )
        assert plan is not None

    workspace = await repository.create_workspace(name)
    user = await repository.create_user(
        f"{name.casefold().replace(' ', '-')}@example.test", name
    )
    assert workspace is not None and user is not None
    membership = await repository.add_membership(
        workspace.public_id, user.id, role="owner"
    )
    assert membership is not None
    territory = None
    if territory_state is not None:
        territory = await repository.claim_territory(
            workspace.public_id,
            f"{territory_state} territory",
            state=territory_state,
        )
        assert territory is not None

    registration_parameters = inspect.signature(auth.register_client).parameters
    if "workspace_id" in registration_parameters:
        client = auth.register_client(
            workspace.public_id, "Claude", (REDIRECT,), scopes
        )
    else:
        client = auth.register_client("Claude", (REDIRECT,), scopes)

    access_grant = None
    if grant:
        access_grant = entitlements.grant_access(
            workspace=workspace.public_id,
            source="manual",
            external_ref=f"grant-{workspace.public_id}",
            profile=profile,
            plan_key=plan_key,
        )

    issuance_parameters = inspect.signature(auth.issue_session).parameters
    if "profile" in issuance_parameters:
        tokens = auth.issue_session(
            workspace.public_id,
            str(user.id),
            client.client_id,
            profile,
            plan="pro",
            territories=(territory_state,) if territory_state else (),
            scopes=scopes,
            audience=audience,
            access_ttl=access_ttl,
        )
    else:
        kwargs = {
            "scopes": scopes,
            "audience": audience,
            "access_ttl": access_ttl,
        }
        if resource is not None:
            kwargs["resource"] = resource
        tokens = auth.issue_session(
            workspace.public_id,
            user.id,
            client.client_id,
            **kwargs,
        )

    return ProvisionedTenant(
        workspace_id=workspace.public_id,
        workspace_row_id=workspace.id,
        user_id=user.id,
        membership_id=membership.id,
        client_id=client.client_id,
        token=tokens.access_token,
        grant_id=access_grant.id if access_grant else None,
        territory_id=territory.id if territory else None,
        plan_id=plan.id if plan else None,
    )


@asynccontextmanager
async def _live_http(app):
    """Serve one ASGI app on an ephemeral loopback port, never port 8000."""
    current = asyncio.current_task()
    baseline_tasks = set(asyncio.all_tasks())
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="on",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await task
        finally:
            sock.close()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 1.5
        pending: set[asyncio.Task] = set()
        while loop.time() < deadline:
            pending = {
                candidate
                for candidate in asyncio.all_tasks()
                if candidate is not current
                and candidate not in baseline_tasks
                and candidate is not task
                and not candidate.done()
            }
            if not pending:
                break
            await asyncio.sleep(0.01)
        assert not pending, (
            "live HTTP fixture left tasks it did not finish: "
            + ", ".join(repr(item.get_coro()) for item in pending)
        )


async def _initialize(app, token: str | None) -> httpx.Response:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "authority-test", "version": "1"},
        },
    }
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://authority.test"
        ) as client:
            response = await client.post("/mcp", headers=headers, json=body)
    return response


def _quota_http_app(config: CreConfig):
    server = FastMCP(name="quota-authority-test")

    @server.tool
    async def search_properties(location: str) -> dict:
        return {"ok": True, "location": location}

    platform = PlatformApi(config)
    install_access_control(
        config,
        runtime_mode="http",
        server=server,
        platform_api=platform,
    )
    return server.http_app(
        path="/mcp",
        transport="http",
        json_response=True,
    )


async def _raw_mcp_request(
    client: httpx.AsyncClient,
    token: str,
    *,
    method: str,
    request_id: int,
    params: dict,
    session_id: str | None = None,
) -> httpx.Response:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        },
    )


async def _raw_initialize(
    client: httpx.AsyncClient,
    token: str,
) -> httpx.Response:
    return await _raw_mcp_request(
        client,
        token,
        method="initialize",
        request_id=1,
        params={
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "raw-authority-test", "version": "1"},
        },
    )


async def _raw_initialized_session(
    client: httpx.AsyncClient,
    token: str,
) -> str:
    initialized = await _raw_initialize(client, token)
    assert initialized.status_code == 200
    session_id = initialized.headers["mcp-session-id"]
    response = await client.post(
        "/mcp",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "mcp-session-id": session_id,
        },
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
    )
    assert response.status_code == 202
    return session_id


async def _raw_close_session(
    client: httpx.AsyncClient,
    token: str,
    session_id: str,
) -> None:
    response = await client.delete(
        "/mcp",
        headers={
            "authorization": f"Bearer {token}",
            "mcp-session-id": session_id,
        },
    )
    assert response.status_code == 200


async def test_real_http_oauth_initializes_lists_and_calls_allowed_tool(tmp_path):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        "Texas Scout",
        profile=Profile.LOCAL_SCOUT,
        territory_state="TX",
    )
    app = create_http_app(config=config)

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            session_id = await _raw_initialized_session(client, tenant.token)
            listed = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/list",
                request_id=2,
                params={},
                session_id=session_id,
            )
            names = {tool["name"] for tool in listed.json()["result"]["tools"]}
            assert "capabilities" in names
            assert "generate_loi" not in names
            called = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=3,
                params={"name": "capabilities", "arguments": {}},
                session_id=session_id,
            )
            result = called.json()["result"]
            await _raw_close_session(client, tenant.token, session_id)

    assert result["isError"] is False
    assert "authority_matrix" in result["structuredContent"]


@pytest.mark.parametrize("case", ["missing", "malformed", "expired", "revoked"])
async def test_bad_tokens_fail_before_mcp_session_allocation(tmp_path, case):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        f"Bad Token {case}",
        access_ttl=(
            timedelta(seconds=-1)
            if case == "expired"
            else timedelta(minutes=15)
        ),
    )
    auth = OAuthSessionStore(config.cache_db_path)
    if case == "revoked":
        session = auth.validate_access(tenant.token)
        assert session is not None
        assert auth.revoke_session(session.session_id)
    token = {
        "missing": None,
        "malformed": "not-an-oauth-token",
        "expired": tenant.token,
        "revoked": tenant.token,
    }[case]

    response = await _initialize(create_http_app(config=config), token)

    assert response.status_code == 401
    assert "mcp-session-id" not in response.headers
    assert response.headers["www-authenticate"].startswith("Bearer ")


async def test_wrong_audience_fails_before_mcp_session_allocation(tmp_path):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        "Wrong Audience",
        audience="another-service",
    )

    response = await _initialize(create_http_app(config=config), tenant.token)

    assert response.status_code == 401
    assert "mcp-session-id" not in response.headers


async def test_wrong_resource_fails_before_mcp_session_allocation(tmp_path):
    config = _config(tmp_path)
    auth = OAuthSessionStore(config.cache_db_path)
    assert "resource" in inspect.signature(auth.issue_session).parameters, (
        "OAuth sessions do not model or enforce a resource indicator"
    )
    tenant = await _provision(
        config,
        "Wrong Resource",
        resource="https://wrong.example/mcp",
    )

    response = await _initialize(create_http_app(config=config), tenant.token)

    assert response.status_code == 401
    assert "mcp-session-id" not in response.headers


async def test_missing_mcp_scope_fails_before_session_allocation(tmp_path):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        "Wrong Scope",
        scopes=DEAL_SCOPES,
    )

    response = await _initialize(create_http_app(config=config), tenant.token)

    assert response.status_code == 403
    assert "mcp-session-id" not in response.headers
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


async def test_static_registry_key_is_rejected_in_oauth_only_hosted_mode(tmp_path):
    config = _config(tmp_path)
    registry = WorkspaceRegistry(config.access_registry_path)
    registry.add_grant("legacy-static-key", "legacy-workspace", Profile.FULL_OPERATOR)

    response = await _initialize(
        create_http_app(config=config),
        "legacy-static-key",
    )

    assert response.status_code == 401
    assert "mcp-session-id" not in response.headers


@pytest.mark.parametrize(
    "disabled_by", ["grant", "expiry", "suspension", "membership"]
)
async def test_current_authority_disables_deal_vault_on_next_request(
    tmp_path, disabled_by
):
    config = _config(tmp_path)
    tenant = await _provision(config, f"Disable {disabled_by}")
    api = starlette_app(config)
    transport = httpx.ASGITransport(app=api)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://platform.test"
    ) as client:
        before = await client.get("/v1/deals", headers=tenant.headers)
        assert before.status_code == 200

        if disabled_by == "grant":
            assert tenant.grant_id is not None
            EntitlementStore(config.cache_db_path).revoke_grant(
                tenant.workspace_id, tenant.grant_id
            )
        elif disabled_by == "expiry":
            EntitlementStore(config.cache_db_path).grant_access(
                workspace=tenant.workspace_id,
                source="manual",
                external_ref=f"grant-{tenant.workspace_id}",
                profile=Profile.FULL_OPERATOR,
                plan_key="pro",
                ends_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        elif disabled_by == "suspension":
            EntitlementStore(config.cache_db_path).set_account_state(
                tenant.workspace_id, "suspended", reason="security review"
            )
        else:
            with sqlite3.connect(config.cache_db_path) as connection:
                connection.execute(
                    "DELETE FROM platform_memberships WHERE id=?",
                    (tenant.membership_id,),
                )

        after = await client.get("/v1/deals", headers=tenant.headers)
    mcp_after = await _initialize(create_http_app(config=config), tenant.token)

    assert after.status_code == 403
    assert after.json()["error"]["code"] == "access_disabled"
    assert mcp_after.status_code == 403
    assert "mcp-session-id" not in mcp_after.headers
    assert 'error="insufficient_scope"' in mcp_after.headers["www-authenticate"]


@pytest.mark.parametrize("disabled_by", ["grant", "expiry", "suspension"])
async def test_disabled_customer_can_read_me_but_not_deals_or_mcp(
    tmp_path, disabled_by
):
    config = _config(tmp_path)
    tenant = await _provision(config, f"Recovery {disabled_by}")
    if disabled_by == "grant":
        assert tenant.grant_id is not None
        EntitlementStore(config.cache_db_path).revoke_grant(
            tenant.workspace_id, tenant.grant_id
        )
    elif disabled_by == "expiry":
        EntitlementStore(config.cache_db_path).grant_access(
            workspace=tenant.workspace_id,
            source="manual",
            external_ref=f"grant-{tenant.workspace_id}",
            profile=Profile.FULL_OPERATOR,
            plan_key="pro",
            ends_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    else:
        EntitlementStore(config.cache_db_path).set_account_state(
            tenant.workspace_id, "suspended", reason="billing"
        )

    api = starlette_app(config)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://platform.test"
    ) as client:
        me = await client.get("/v1/me", headers=tenant.headers)
        entitlements = await client.get(
            "/v1/entitlements", headers=tenant.headers
        )
        deals = await client.get("/v1/deals", headers=tenant.headers)
    mcp_response = await _initialize(create_http_app(config=config), tenant.token)

    assert me.status_code == 200
    assert entitlements.status_code == 200
    assert deals.status_code == 403
    assert mcp_response.status_code == 403
    assert 'error="insufficient_scope"' in mcp_response.headers["www-authenticate"]


async def test_territory_change_applies_to_next_mcp_call_without_refresh(tmp_path):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        "Moving Territory",
        profile=Profile.LOCAL_SCOUT,
        territory_state="TX",
    )
    assert tenant.territory_id is not None
    repository = PlatformRepository(config.cache_db_path)
    app = create_http_app(config=config)

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            session_id = await _raw_initialized_session(client, tenant.token)
            first = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=2,
                params={
                    "name": "save_search",
                    "arguments": {
                        "name": "Texas box",
                        "location": "Austin, TX",
                    },
                },
                session_id=session_id,
            )
            assert first.json()["result"]["isError"] is False

            changed = await repository.update_territory(
                tenant.workspace_id,
                tenant.territory_id,
                state="FL",
            )
            assert changed is not None

            rejected = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=3,
                params={
                    "name": "save_search",
                    "arguments": {
                        "name": "Stale Texas box",
                        "location": "Austin, TX",
                    },
                },
                session_id=session_id,
            )
            rejected_result = rejected.json()["result"]
            assert rejected_result["isError"] is True
            assert "territor" in rejected_result["content"][0]["text"].casefold()
            await _raw_close_session(client, tenant.token, session_id)


async def test_workspace_cannot_be_selected_through_http_or_mcp_input(tmp_path):
    config = _config(tmp_path)
    alpha = await _provision(config, "Authority Alpha")
    beta = await _provision(config, "Authority Beta")

    api = starlette_app(config)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://platform.test"
    ) as client:
        created = await client.post(
            f"/v1/deals?workspace_id={beta.workspace_id}",
            headers={
                **alpha.headers,
                "x-workspace-id": beta.workspace_id,
            },
            json={
                "deal_ref": "manual:authority",
                "title": "Alpha only",
                "workspace_id": beta.workspace_id,
                "payload": {"workspace_id": beta.workspace_id},
            },
        )
        beta_deals = await client.get("/v1/deals", headers=beta.headers)

    assert created.status_code == 201
    assert beta_deals.json()["deals"] == []

    app = create_http_app(config=config)
    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            session_id = await _raw_initialized_session(client, alpha.token)
            response = await _raw_mcp_request(
                client,
                alpha.token,
                method="tools/call",
                request_id=2,
                params={
                    "name": "capabilities",
                    "arguments": {
                        "workspace_id": beta.workspace_id,
                        "workspace": beta.workspace_id,
                        "profile": "full_operator",
                    },
                },
                session_id=session_id,
            )
            result = response.json()["result"]
            assert "authority_matrix" in result["structuredContent"]
            await _raw_close_session(client, alpha.token, session_id)


def test_client_registration_cannot_claim_or_preselect_workspace(tmp_path):
    store = OAuthSessionStore(tmp_path / "platform.db")

    assert "workspace_id" not in inspect.signature(store.register_client).parameters
    client = store.register_client("Claude", (REDIRECT,), ALL_SCOPES)
    assert not hasattr(client, "workspace_id")


def test_session_issuance_has_no_profile_plan_or_territory_authority_inputs(tmp_path):
    store = OAuthSessionStore(tmp_path / "platform.db")
    parameters = inspect.signature(store.issue_session).parameters

    assert {"profile", "plan", "territories"}.isdisjoint(parameters)


@pytest.mark.parametrize(
    "path",
    (
        "/authorize?user_id=7&workspace_id=ws-invented",
        "/register",
        "/oauth/register",
        "/token",
        "/oauth/token",
    ),
)
async def test_identity_dependent_public_authorize_endpoint_is_not_exposed(
    tmp_path, path
):
    config = _config(tmp_path)
    app = create_http_app(config=config)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://authority.test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 404


async def test_identity_must_be_a_real_active_membership_before_issuance(tmp_path):
    config = _config(tmp_path)
    repository = PlatformRepository(config.cache_db_path)
    workspace = await repository.create_workspace("Identity Boundary")
    user = await repository.create_user("identity@example.test", "Identity")
    assert workspace is not None and user is not None
    store = OAuthSessionStore(config.cache_db_path)
    registration_parameters = inspect.signature(store.register_client).parameters
    if "workspace_id" in registration_parameters:
        client = store.register_client(
            workspace.public_id, "Claude", (REDIRECT,), ALL_SCOPES
        )
    else:
        client = store.register_client("Claude", (REDIRECT,), ALL_SCOPES)

    issuance_parameters = inspect.signature(store.issue_session).parameters
    with pytest.raises(ValueError, match="membership|identity"):
        if "profile" in issuance_parameters:
            store.issue_session(
                workspace.public_id,
                str(user.id),
                client.client_id,
                Profile.FULL_OPERATOR,
                scopes=ALL_SCOPES,
            )
        else:
            store.issue_session(
                workspace.public_id,
                user.id,
                client.client_id,
                scopes=ALL_SCOPES,
            )


async def test_oauth_quota_comes_from_live_plan_and_updates_in_established_session(
    tmp_path,
):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        "Live Quota",
        plan_quotas={"search": 1},
    )
    assert tenant.plan_id is not None
    repository = PlatformRepository(config.cache_db_path)
    app = _quota_http_app(config)

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            session_id = await _raw_initialized_session(client, tenant.token)
            first = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=2,
                params={
                    "name": "search_properties",
                    "arguments": {"location": "OH"},
                },
                session_id=session_id,
            )
            assert first.json()["result"]["structuredContent"]["ok"] is True
            limited = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=3,
                params={
                    "name": "search_properties",
                    "arguments": {"location": "OH"},
                },
                session_id=session_id,
            )
            limited_result = limited.json()["result"]
            assert limited_result["isError"] is True
            assert "quota" in limited_result["content"][0]["text"].casefold()

            updated = await repository.update_plan(
                tenant.plan_id,
                daily_quotas={"search": 2},
            )
            assert updated is not None
            second = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/call",
                request_id=4,
                params={
                    "name": "search_properties",
                    "arguments": {"location": "OH"},
                },
                session_id=session_id,
            )
            assert second.json()["result"]["structuredContent"]["ok"] is True
            await _raw_close_session(client, tenant.token, session_id)


@pytest.mark.parametrize("case", ["missing", "malformed"])
async def test_missing_or_malformed_live_plan_fails_closed(tmp_path, case):
    config = _config(tmp_path)
    tenant = await _provision(
        config,
        f"Bad Live Plan {case}",
        plan_key="missing-plan" if case == "missing" else "pro",
        provision_plan=case != "missing",
    )
    if case == "malformed":
        with sqlite3.connect(config.cache_db_path) as connection:
            connection.execute(
                "UPDATE platform_plans SET daily_quotas='not-json' WHERE key='pro'"
            )

    response = await _initialize(create_http_app(config=config), tenant.token)

    assert response.status_code == 403
    assert "mcp-session-id" not in response.headers
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


@pytest.mark.parametrize("disabled_by", ["entitlement", "account", "membership"])
async def test_established_session_live_disable_remains_403(
    tmp_path,
    disabled_by,
):
    config = _config(tmp_path)
    tenant = await _provision(config, f"Established Disable {disabled_by}")
    app = create_http_app(config=config)

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            initialized = await _raw_initialize(client, tenant.token)
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]

            if disabled_by == "entitlement":
                assert tenant.grant_id is not None
                EntitlementStore(config.cache_db_path).revoke_grant(
                    tenant.workspace_id,
                    tenant.grant_id,
                )
            elif disabled_by == "account":
                EntitlementStore(config.cache_db_path).set_account_state(
                    tenant.workspace_id,
                    "suspended",
                    reason="security review",
                )
            else:
                with sqlite3.connect(config.cache_db_path) as connection:
                    connection.execute(
                        "DELETE FROM platform_memberships WHERE id=?",
                        (tenant.membership_id,),
                    )

            response = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/list",
                request_id=2,
                params={},
                session_id=session_id,
            )

    assert response.status_code == 403
    assert response.headers.get("mcp-session-id") in {None, session_id}


@pytest.mark.parametrize("revoked_by", ["session", "client"])
async def test_established_session_token_or_client_revoke_remains_401(
    tmp_path,
    revoked_by,
):
    config = _config(tmp_path)
    tenant = await _provision(config, f"Established Revoke {revoked_by}")
    app = create_http_app(config=config)

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            initialized = await _raw_initialize(client, tenant.token)
            assert initialized.status_code == 200
            session_id = initialized.headers["mcp-session-id"]

            auth = OAuthSessionStore(config.cache_db_path)
            if revoked_by == "session":
                session = auth.validate_access(tenant.token)
                assert session is not None
                assert auth.revoke_session(session.session_id)
            else:
                assert auth.revoke_client(tenant.client_id)

            response = await _raw_mcp_request(
                client,
                tenant.token,
                method="tools/list",
                request_id=2,
                params={},
                session_id=session_id,
            )

    assert response.status_code == 401
    assert response.headers.get("mcp-session-id") in {None, session_id}


async def test_http_cleanup_never_cancels_unowned_same_named_task(tmp_path):
    release = asyncio.Event()

    async def _shutdown_watcher():
        await release.wait()

    unowned = asyncio.create_task(_shutdown_watcher())
    try:
        app = create_http_app(config=_config(tmp_path))
        async with _live_http(app) as base_url:
            async with httpx.AsyncClient(base_url=base_url) as client:
                response = await _raw_initialize(client, "not-a-valid-token")
        assert response.status_code == 401
        assert not unowned.cancelled()
    finally:
        release.set()
        if not unowned.done():
            await unowned
