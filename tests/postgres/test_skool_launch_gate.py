"""The Skool launch gate, on the real hosted PostgreSQL path.

`tests/platform/test_private_beta_launch_gate.py` proves this sequence against
the sanctioned test adapter, whose stores are SQLite files. This proves the same
claim where it has to hold: the production `create_http_app` boot, the twelve
platform authority stores answering out of PostgreSQL, and a real MCP client
over a real loopback socket.

The claim: a qualifying Skool member gets MCP access, and when that membership
ends, an already-issued and still-unexpired OAuth token stops authorizing
protected calls on the very next request.

The access token is issued with a twelve-hour TTL on purpose. If the denial at
the end could be explained by expiry, this test would prove nothing about
revocation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.dbapi import clear_platform_backend
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.surface import CUSTOMER_SURFACE
from tests.platform.test_authoritative_oauth import (
    REDIRECT,
    _live_http,
    _raw_initialized_session,
    _raw_mcp_request,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
MCP_SCOPE = "mcp:tools"
TIER = "community_1:level_local"
MEMBER_ID = "member_postgres_launch_gate"
REASON = {
    "reason_code": "entitlement_correction",
    "reason": "Verified against the internal Skool operations runbook.",
}

# Both names must be real on the customer surface. Asserting that an invented
# name is absent from tools/list passes no matter what the server does.
ENTITLED_TOOL = "cre_pipeline"
UNENTITLED_TOOL = "cre_offer"
LOCAL_SCOUT_TOOL_COUNT = 8


@pytest.fixture
def hosted_app(postgres_database, tmp_path, monkeypatch):
    """The production hosted app, booted against a live migrated cluster."""
    from cre_mcp.server import create_http_app

    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()

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
    monkeypatch.setenv("CRE_CLERK_SECRET_KEY", "sk_test_launch_gate")
    monkeypatch.setenv("CRE_STRIPE_API_KEY", "sk_test_launchgatenotarealkey")
    monkeypatch.setenv("CRE_STRIPE_WEBHOOK_SECRET", "whsec_launch_gate")
    monkeypatch.setenv("CRE_SKOOL_WEBHOOK_SECRET", "whsec_skool_launch_gate")

    config = CreConfig(
        _env_file=None,
        cache_db_path=tmp_path / "must-not-be-created.db",
        stripe_webhook_secret="whsec_launch_gate",
        skool_webhook_secret="whsec_skool_launch_gate",
        skool_community_urls={"community_1": "https://www.skool.com/medawar-cre"},
        skool_tier_mappings={
            "community_1:level_local": {
                "plan_key": "local",
                "profile": "local_scout",
            },
            "community_1:level_national": {
                "plan_key": "national",
                "profile": "national_scout",
            },
        },
    )
    app = create_http_app(config=config, path="/mcp")
    try:
        yield app, config, app_dsn
    finally:
        app.state.hosted_persistence.close()
        clear_platform_backend()


def _one(dsn: str, statement: str, parameters=()):
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement, parameters).fetchone()


def _skool_grant(dsn: str, workspace_row_id: int):
    row = _one(
        dsn,
        "SELECT status, profile, plan_key FROM platform_access_grants "
        "WHERE workspace_id=%s AND source='skool' ORDER BY id DESC LIMIT 1",
        (workspace_row_id,),
    )
    return None if row is None else (str(row[0]), str(row[1]), str(row[2]))


def _confirmed_roster(member_id: str) -> dict:
    """A complete, confirmed operator review naming exactly this member."""
    return {
        "community_id": "community_1",
        "source": "operator_members_review",
        "observed_at": NOW.isoformat(),
        "confidence": "confirmed",
        "complete": True,
        "members": [
            {"member_id": member_id, "status": "active", "level_id": "level_local"}
        ],
    }


async def test_skool_access_is_granted_and_revoked_on_the_postgresql_path(
    hosted_app,
):
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence
    assert bundle.backend == "postgres"

    platform = bundle.platform_api
    service = platform.skool_lifecycle
    repository = PlatformRepository(config=config)

    # 1. Provision the customer, entirely through the platform stores, which
    #    now write to PostgreSQL.
    for key in ("local", "national", "operator", "jv"):
        if not any(item.key == key for item in await repository.list_plans()):
            assert await repository.create_plan(key, key.title()) is not None
    workspace = await repository.create_workspace("PostgreSQL Launch Gate")
    assert workspace is not None
    customer = await repository.create_user(
        "launch-gate-customer@example.test", "Launch Gate Customer"
    )
    assert customer is not None
    assert (
        await repository.add_membership(
            workspace.public_id, customer.id, role="owner"
        )
        is not None
    )
    assert (
        await repository.claim_territory(
            workspace.public_id, "TX territory", state="TX"
        )
        is not None
    )

    # The operator is a separate human. Binding and revoking a Skool member are
    # internal actions, never self-service.
    operator = await repository.create_user(
        "launch-gate-operator@example.test", "Launch Gate Operator"
    )
    assert operator is not None
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_internal_admins"
            "(user_id, role, active, created_at, updated_at) "
            "VALUES (%s,'platform_admin',1,%s,%s)",
            (operator.id, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()

    # 2. Joining is an audited operator task that binds the exact member id and
    #    deliberately grants nothing on its own.
    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=operator.id,
        subject_user_id=customer.id,
        tier=TIER,
        **REASON,
    )
    completed = service.complete_join_task(
        workspace.public_id,
        task["id"],
        actor_user_id=operator.id,
        external_member_id=MEMBER_ID,
        completion_source="manual_admin_invite",
        **REASON,
    )
    mapping_id = int(completed["task"]["external_mapping_id"])
    assert completed["grant_created"] is False
    assert _skool_grant(dsn, workspace.id) is None

    # Access arrives only from a complete, confirmed current-state review.
    reconciled = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=operator.id,
        artifact=_confirmed_roster(MEMBER_ID),
        now=NOW,
        **REASON,
    )
    assert reconciled["certainty"] == "confirmed"
    assert _skool_grant(dsn, workspace.id) == ("active", "local_scout", "local")

    # 3. The session carries identity and scope and nothing else. No profile,
    #    plan, or territory argument exists to pass, so authority is re-derived
    #    from live state on every request.
    auth = OAuthSessionStore(config.cache_db_path)
    client_record = auth.register_client("Claude", (REDIRECT,), (MCP_SCOPE,))
    tokens = auth.issue_session(
        workspace.public_id,
        customer.id,
        client_record.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    )
    token = tokens.access_token

    async with _live_http(app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as client:
            session_id = await _raw_initialized_session(client, token)

            # 4. tools/list exposes exactly the entitled surface.
            listed = await _raw_mcp_request(
                client,
                token,
                method="tools/list",
                request_id=2,
                params={},
                session_id=session_id,
            )
            names = {tool["name"] for tool in listed.json()["result"]["tools"]}
            assert len(names) == LOCAL_SCOUT_TOOL_COUNT
            assert ENTITLED_TOOL in names
            assert UNENTITLED_TOOL in set(CUSTOMER_SURFACE.tools)
            assert UNENTITLED_TOOL not in names

            # 5. A tool call is admitted or fails closed -- never served
            #    unadmitted. The atomic-admission port is incomplete (see
            #    `test_a_tool_call_fails_closed_until_atomic_admission_is_ported`
            #    below for the exact diagnosis), so today this is the closed
            #    branch. It is asserted rather than skipped because "refused"
            #    and "served without admission" are the two outcomes that
            #    matter, and only one of them is acceptable in either state.
            allowed = await _raw_mcp_request(
                client,
                token,
                method="tools/call",
                request_id=3,
                params={
                    "name": ENTITLED_TOOL,
                    "arguments": {"action": "list_searches", "arguments": {}},
                },
                session_id=session_id,
            )
            assert allowed.status_code == 200
            if allowed.json()["result"]["isError"]:
                # The exact refusal, not a substring that any denial matches:
                # this is the admission function reporting that it found no
                # certified credential row, which is the gap named below.
                assert allowed.json()["result"]["content"][0]["text"] == (
                    "access denied: live session authority is unavailable"
                )

            # 6. The unentitled tool is refused when named directly, not merely
            #    hidden from the listing.
            hidden = await _raw_mcp_request(
                client,
                token,
                method="tools/call",
                request_id=4,
                params={"name": UNENTITLED_TOOL, "arguments": {}},
                session_id=session_id,
            )
            assert hidden.status_code in {200, 403}
            if hidden.status_code == 200:
                payload = hidden.json()
                assert "error" in payload or payload["result"]["isError"] is True

            # 7. Membership ends. Manual revoke is the only trustworthy removal
            #    signal Skool exposes today.
            report = service.manual_revoke(
                workspace.public_id,
                mapping_id,
                actor_user_id=operator.id,
                now=NOW,
                **REASON,
            )
            assert report["grant_status"] != "active"
            assert report["oauth_sessions_revoked"] >= 1

            # 8. The gate. The same token is well inside its 12-hour TTL, and
            #    the protected call asserted here is `tools/list` -- which
            #    succeeded at step 4 under the same token and session, so a
            #    refusal now can only come from the revocation.
            after_revoke = await _raw_mcp_request(
                client,
                token,
                method="tools/list",
                request_id=5,
                params={},
                session_id=session_id,
            )

    # Asserted as the exact door. Two independent mechanisms deny here -- the
    # session is revoked and the grant is gone -- and a loose `in {401, 403}`
    # cannot tell them apart: neutering OAuth session revocation still yields a
    # 403 from the entitlement check, so the loose form passes while the
    # requirement that an already-issued token stops authorizing has silently
    # regressed.
    assert after_revoke.status_code == 401, (
        "an ended Skool membership must invalidate the already-issued token "
        f"itself, not merely fail the entitlement check; got "
        f"{after_revoke.status_code}"
    )
    assert after_revoke.json()["error"] == "invalid_token"

    # The revocation is durable, not process-local: a fresh read of PostgreSQL
    # shows the grant ended and the session revoked.
    assert _skool_grant(dsn, workspace.id)[0] != "active"
    assert _one(
        dsn,
        "SELECT count(*) FROM platform_oauth_sessions "
        "WHERE workspace_id=%s AND revoked_at IS NOT NULL",
        (workspace.public_id,),
    )[0] >= 1

    # And nothing was written to a local file at any point.
    assert not Path(config.cache_db_path).exists()


async def test_a_tool_call_fails_closed_until_atomic_admission_is_ported(
    hosted_app,
):
    """The one thing the hosted path still refuses, named exactly.

    `tools/list`, authorization, entitlement filtering, territory and Skool
    revocation all work on PostgreSQL. `tools/call` does not, and the reason is
    specific rather than general.

    `medawarcre.atomic_admit_tool_call` (migration 0003) re-resolves the whole
    authority in SQL from a `credential` CTE over `medawarcre.oauth_sessions`,
    `access_grants`, `plans` and `territories`. Nothing writes those rows: the
    product issues sessions through `OAuthSessionStore` into
    `platform_oauth_sessions` and grants through `EntitlementStore` into
    `platform_access_grants`. So the function finds no credential and returns
    `authority_missing`, and the middleware refuses.

    Migration 0012 closes the identity half of this -- users, workspaces and
    memberships now project -- which is why admission reaches its authority
    check at all instead of raising on `_uuid("41")`. Projecting the session,
    grant, plan and territory rows as well is the remaining work.

    What this test pins meanwhile is the property that must hold in either
    state: an unadmitted tool call is refused with a fail-closed message and is
    never executed. If someone makes admission optional to get a green tool
    call, this fails.
    """
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence

    from cre_mcp.access.context import TenantContext

    context = TenantContext(
        workspace_id="ws_absent_from_certified_schema",
        profile="local_scout",
        plan="local",
        quota_limits={"search": 100},
        territories=("TX",),
        active=True,
        trusted=False,
        display_name="Unprojected",
        actor_id="4242",
        session_id="sess_unprojected",
    )
    outcome = bundle.admission_repository.admit(
        context,
        "cre_pipeline",
        {"action": "list_searches"},
        quota_bucket="search",
        requires_approval=False,
    )
    assert outcome.decision == "denied"
    assert outcome.reason_code == "authority_missing"
    # The identity projection still ran and returned the platform's own
    # identifiers, so a fix to the authority half does not also have to
    # re-derive these.
    assert outcome.actor_user_id == "4242"
    assert outcome.session_id == "sess_unprojected"
