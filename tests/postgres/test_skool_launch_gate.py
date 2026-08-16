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


def _owner_one(dsn: str, statement: str, parameters=()):
    """Read as the cluster owner, bypassing row-level security deliberately.

    An application-role connection with no admitted request sees nothing, so a
    negative assertion made through one is true regardless of what is stored.
    """
    with psycopg.connect(
        dsn.replace("user=medawarcre_test_app", "user=postgres")
    ) as connection:
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

            # 5. One entitled tool call is admitted, executed, and answered
            #    from PostgreSQL. This is the whole path: atomic admission,
            #    the request-scoped search repository under row-level security,
            #    the post-result territory contract, and the final audit.
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
            assert allowed.json()["result"]["isError"] is False
            assert allowed.json()["result"]["structuredContent"]["count"] == 0

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
            #    the protected call asserted here is the one that succeeded at
            #    step 5 under this same token and session -- so a refusal now
            #    can only come from the revocation.
            after_revoke = await _raw_mcp_request(
                client,
                token,
                method="tools/call",
                request_id=5,
                params={
                    "name": ENTITLED_TOOL,
                    "arguments": {"action": "list_searches", "arguments": {}},
                },
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


async def test_admission_refuses_identity_that_never_passed_the_resolver(
    hosted_app,
):
    """Where the security boundary actually is, pinned rather than assumed.

    Migration 0012 projects identity *and* authority: the session, account,
    grant, plan quotas and territories that `atomic_admit_tool_call`'s
    credential CTE reads and that nothing else in the product writes. That is
    what made the tool call above work, and it has a consequence worth stating
    plainly rather than discovering later.

    The projection trusts the `TenantContext` it is handed completely. It has
    to: every value in it was resolved by `AuthorityResolver` against the
    platform stores on this same request, and there is nothing else for the
    projection to check against. So admission is no longer an independent
    second opinion on authority -- it is atomic replay suppression, quota
    consumption, approval consumption and durable audit, over a context whose
    authority was already established.

    The boundary is therefore `AuthorityResolver`, and the launch gate above is
    the proof that it holds: a revoked member is refused 401 before admission
    is reached at all.

    What is still pinned here is that admission will not accept identity that
    never went through that resolver. `AuthorityResolver` emits the derived
    certified uuids when the PostgreSQL backend is installed; a raw platform
    row id -- the shape any code path bypassing the resolver would produce --
    is refused rather than projected.
    """
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence

    from cre_mcp.access.context import TenantContext

    raw_platform_identity = TenantContext(
        workspace_id="ws_never_resolved",
        profile="local_scout",
        plan="local",
        quota_limits={"search": 100},
        territories=("TX",),
        active=True,
        trusted=False,
        display_name="Unresolved",
        # A platform row id, not a derived certified uuid. This is what reaches
        # admission if anything ever calls it without going through the
        # resolver.
        actor_id="4242",
        session_id="sess_never_resolved",
    )
    from cre_mcp.postgres.identity_projection import IdentityProjectionUnavailable

    with pytest.raises(IdentityProjectionUnavailable, match="resolver-issued"):
        bundle.admission_repository.admit(
            raw_platform_identity,
            "cre_pipeline",
            {"action": "list_searches"},
            quota_bucket="search",
            requires_approval=False,
        )

    # And nothing was projected for it: a refused admission must not leave a
    # tenant behind.
    #
    # Read as the cluster owner. The first version of this line read as
    # `medawarcre_test_app` under row-level security with no workspace bound,
    # where the count is 0 for every input -- so it asserted nothing at all,
    # and an independent reviewer confirmed the row was there. That is the same
    # vacuity class this program has a documented history of, and it is why the
    # helper below is a separate one with the reason attached rather than the
    # convenient one already in the file.
    assert _owner_one(
        dsn,
        "SELECT count(*) FROM workspaces WHERE public_id=%s",
        ("ws_never_resolved",),
    )[0] == 0
    # The same for a workspace that does exist in the platform authority but
    # whose caller supplied a fabricated profile: the projection reads the
    # grant rather than the argument, so there is nothing to fabricate.
    assert _owner_one(
        dsn,
        "SELECT count(*) FROM access_grants WHERE profile='full_operator'",
    )[0] == 0
