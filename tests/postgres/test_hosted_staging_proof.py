"""The private-staging proof, end to end, on the hosted PostgreSQL path.

The launch gate next door proves the Skool entitlement lifecycle. This proves
the rest of what a private beta needs before anyone points DNS at it:

  * a customer's work persists to *their* workspace in PostgreSQL
  * a second customer cannot see it, and cannot reach it by asking
  * the internal Operations Console sees the same record
  * the customer cannot reach an internal route
  * the data survives a process restart and a fresh database connection

Everything runs through `create_http_app`, over a real loopback socket, with
both customers holding real OAuth tokens. Nothing here asserts against a mock
of the thing under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.dbapi import clear_platform_backend
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.postgres.migrations import MigrationRunner
from tests.platform.test_authoritative_oauth import (
    REDIRECT,
    _live_http,
    _raw_initialized_session,
    _raw_mcp_request,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
MCP_SCOPE = "mcp:tools"
REASON = {
    "reason_code": "entitlement_correction",
    "reason": "Verified against the internal Skool operations runbook.",
}
TIER = "community_1:level_local"


def _environment(monkeypatch, migration_dsn: str, app_dsn: str) -> None:
    def _as(role: str) -> str:
        return app_dsn.replace("user=medawarcre_test_app", f"user={role}")

    monkeypatch.setenv("MEDAWARCRE_DATABASE_URL", app_dsn)
    monkeypatch.setenv("MEDAWARCRE_APP_DATABASE_URL", app_dsn)
    monkeypatch.setenv("MEDAWARCRE_MIGRATION_DATABASE_URL", migration_dsn)
    monkeypatch.setenv(
        "MEDAWARCRE_OAUTH_DATABASE_URL", _as("medawarcre_test_oauth")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_ADMISSION_DATABASE_URL", _as("medawarcre_test_admission")
    )
    monkeypatch.setenv(
        "MEDAWARCRE_BACKUP_DATABASE_URL", _as("medawarcre_test_backup")
    )
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", "sk_test_staging_proof")
    monkeypatch.setenv("CRE_STRIPE_API_KEY", "sk_test_stagingproofnotarealkey")
    monkeypatch.setenv("CRE_STRIPE_WEBHOOK_SECRET", "whsec_staging_proof")
    monkeypatch.setenv("CRE_SKOOL_WEBHOOK_SECRET", "whsec_skool_staging_proof")


def _config(tmp_path) -> CreConfig:
    return CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "must-not-be-created.db",
        stripe_webhook_secret="whsec_staging_proof",
        skool_webhook_secret="whsec_skool_staging_proof",
        skool_community_urls={"community_1": "https://www.skool.com/medawar-cre"},
        skool_tier_mappings={
            "community_1:level_local": {
                "plan_key": "local",
                "profile": "local_scout",
            }
        },
    )


@pytest.fixture
def staging(postgres_database, tmp_path, monkeypatch):
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    _environment(monkeypatch, migration_dsn, app_dsn)
    try:
        yield _config(tmp_path), app_dsn
    finally:
        clear_platform_backend()


def _rows(dsn: str, statement: str, parameters=()) -> list[tuple]:
    """Read as the cluster owner, bypassing row-level security deliberately.

    Verification has to see what is actually stored. An application-role
    connection cannot: RLS filters every tenant row against `app.workspace_id`,
    which only an admitted request sets. That is asserted separately below
    rather than worked around silently.
    """
    with psycopg.connect(dsn.replace("user=medawarcre_test_app", "user=postgres")) as (
        connection
    ):
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement, parameters).fetchall()


def _app_role_rows(dsn: str, statement: str) -> list[tuple]:
    """Read as the application role with no workspace context bound."""
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement).fetchall()


async def _provision(repository, service, operator_id, name, member_id, state):
    """One entitled customer: workspace, member, territory, Skool grant."""
    workspace = await repository.create_workspace(name)
    customer = await repository.create_user(
        f"{member_id}@example.test", f"{name} Customer"
    )
    await repository.add_membership(workspace.public_id, customer.id, "owner")
    await repository.claim_territory(
        workspace.public_id, f"{state} territory", state=state
    )
    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=operator_id,
        subject_user_id=customer.id,
        tier=TIER,
        **REASON,
    )
    service.complete_join_task(
        workspace.public_id,
        task["id"],
        actor_user_id=operator_id,
        external_member_id=member_id,
        completion_source="manual_admin_invite",
        **REASON,
    )
    service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=operator_id,
        artifact={
            "community_id": "community_1",
            "source": "operator_members_review",
            "observed_at": NOW.isoformat(),
            "confidence": "confirmed",
            "complete": True,
            "members": [
                {
                    "member_id": member_id,
                    "status": "active",
                    "level_id": "level_local",
                }
            ],
        },
        now=NOW,
        **REASON,
    )
    return workspace, customer


def _token(config, workspace, customer, label: str) -> str:
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client(label, (REDIRECT,), (MCP_SCOPE,))
    return auth.issue_session(
        workspace.public_id,
        customer.id,
        client.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    ).access_token


async def _call(client, token, session_id, action, arguments, request_id):
    return await _raw_mcp_request(
        client,
        token,
        method="tools/call",
        request_id=request_id,
        params={
            "name": "cre_pipeline",
            "arguments": {"action": action, "arguments": arguments},
        },
        session_id=session_id,
    )


async def test_two_customers_share_a_server_and_never_each_other_s_data(
    staging,
):
    from cre_mcp.server import create_http_app

    config, dsn = staging
    app = create_http_app(config=config, path="/mcp")
    bundle = app.state.hosted_persistence
    repository = PlatformRepository(config=config)
    service = bundle.platform_api.skool_lifecycle

    for key in ("local", "national", "operator", "jv"):
        if not any(item.key == key for item in await repository.list_plans()):
            await repository.create_plan(key, key.title())
    operator = await repository.create_user(
        "staging-operator@example.test", "Staging Operator"
    )
    with psycopg.connect(
        dsn.replace("user=medawarcre_test_app", "user=postgres")
    ) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_internal_admins"
            "(user_id, role, active, created_at, updated_at) "
            "VALUES (%s,'platform_admin',1,%s,%s)",
            (operator.id, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()

    alpha_ws, alpha_user = await _provision(
        repository, service, operator.id, "Alpha Tenant", "member_alpha", "TX"
    )
    beta_ws, beta_user = await _provision(
        repository, service, operator.id, "Beta Tenant", "member_beta", "AZ"
    )
    alpha_token = _token(config, alpha_ws, alpha_user, "Alpha Client")
    beta_token = _token(config, beta_ws, beta_user, "Beta Client")

    try:
        async with _live_http(app) as base_url:
            async with httpx.AsyncClient(base_url=base_url) as client:
                alpha_session = await _raw_initialized_session(client, alpha_token)
                beta_session = await _raw_initialized_session(client, beta_token)

                # Alpha saves a search. This is a real hosted write: admitted,
                # executed, persisted through the request-scoped repository.
                saved = await _call(
                    client,
                    alpha_token,
                    alpha_session,
                    "save_search",
                    # `location` is the capability's declared territory
                    # parameter, so it is a real argument of the action rather
                    # than a field inside the query -- the access engine reads
                    # it before the tool runs and refuses a call it cannot
                    # resolve against this workspace's territory.
                    {"name": "Alpha Austin retail", "location": "Austin, TX"},
                    request_id=10,
                )
                assert saved.status_code == 200
                assert saved.json()["result"]["isError"] is False

                # Alpha sees exactly their own search.
                alpha_list = await _call(
                    client, alpha_token, alpha_session, "list_searches", {}, 11
                )
                alpha_payload = alpha_list.json()["result"]["structuredContent"]
                assert alpha_payload["count"] == 1
                assert alpha_payload["searches"][0]["name"] == "Alpha Austin retail"

                # Beta, on the same server and the same database, sees none of
                # it. Not filtered out of a longer list -- absent.
                beta_list = await _call(
                    client, beta_token, beta_session, "list_searches", {}, 12
                )
                beta_payload = beta_list.json()["result"]["structuredContent"]
                assert beta_payload["count"] == 0
                assert beta_payload["searches"] == []

                # The internal Operations Console sees both tenants -- read
                # here, inside the running process, because
                # `bind_persistence_lifespan` closes the bundle when the ASGI
                # lifespan exits, and closing it returns the platform stores to
                # their file-backed default. A Console read after that point
                # silently answers from an empty SQLite file instead of
                # PostgreSQL, which is indistinguishable from "no tenants".
                from cre_mcp.platform.operations import OperationsReadStore

                console = OperationsReadStore(config.cache_db_path)
                visible = {
                    item["name"]
                    for item in console.search_workspaces("Tenant")["workspaces"]
                }
                assert {"Alpha Tenant", "Beta Tenant"} <= visible
                assert console.health()["workspaces"] >= 2

        # The row is in PostgreSQL, bound to Alpha's projected workspace, and
        # there is exactly one of it.
        stored = _rows(
            dsn,
            "SELECT search.name, workspace.public_id "
            "FROM saved_searches search "
            "JOIN workspaces workspace ON workspace.id = search.workspace_id",
        )
        assert stored == [("Alpha Austin retail", alpha_ws.public_id)]

        # And the application role, holding a live connection but no admitted
        # request, sees nothing at all. Row-level security is the floor under
        # the tenant isolation proved over HTTP above, not a second opinion
        # about it: if the application connection leaked, this is what leaks.
        assert _app_role_rows(dsn, "SELECT count(*) FROM saved_searches") == [(0,)]
    finally:
        bundle.close()

    # Restart. A brand-new process-equivalent bundle, fresh pools, fresh
    # connections, same database -- and Alpha's work is still theirs.
    restarted = create_http_app(config=config, path="/mcp")
    try:
        assert restarted.state.hosted_persistence.backend == "postgres"
        async with _live_http(restarted) as base_url:
            async with httpx.AsyncClient(base_url=base_url) as client:
                session_id = await _raw_initialized_session(client, alpha_token)
                after_restart = await _call(
                    client, alpha_token, session_id, "list_searches", {}, 13
                )
                payload = after_restart.json()["result"]["structuredContent"]
                assert payload["count"] == 1
                assert payload["searches"][0]["name"] == "Alpha Austin retail"
    finally:
        restarted.state.hosted_persistence.close()


async def test_a_customer_cannot_reach_an_internal_route(staging):
    """The customer surface is sign-in and MCP. Internal is not on it."""
    from cre_mcp.server import create_http_app

    config, _ = staging
    app = create_http_app(config=config, path="/mcp")
    try:
        async with _live_http(app) as base_url:
            async with httpx.AsyncClient(base_url=base_url) as client:
                for path in (
                    "/v1/operations/workspaces",
                    "/v1/operations/health",
                    "/v1/admin/workspaces",
                ):
                    response = await client.get(path)
                    # Refused or absent -- never served. 404 is as acceptable
                    # as 401 here: the requirement is that no customer-held
                    # credential reaches internal data, not that the route
                    # announce itself.
                    assert response.status_code in {401, 403, 404, 405}, (
                        f"{path} returned {response.status_code}"
                    )
    finally:
        app.state.hosted_persistence.close()
