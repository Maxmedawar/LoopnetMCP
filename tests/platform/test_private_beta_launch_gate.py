"""The private-beta launch gate, proven once end to end over loopback HTTP.

The founder's first launch gate is a single claim: a qualifying Skool member
gets MCP access, and when that membership ends, protected MCP access stops
promptly -- an already-issued, still-unexpired OAuth token must stop
authorizing protected calls without waiting for it to expire.

Every step below drives the real hosted ASGI application over a real socket:
the real access middleware, the real customer surface catalog, the real OAuth
session store, and the real Skool lifecycle service. Nothing asserts against a
mock of the thing under test.

Scope of the proof, stated exactly because it is narrower than "staging works":
this pins the *authority lifecycle*. The bundle here is the sanctioned test
adapter in `tests/hosted_helpers.py`, so it does not exercise the production
PostgreSQL hosting path.

This paragraph previously said the production path "still refuses by design
until the request-scoped domain repositories are certified". That is no longer
true — `build_postgres_hosted_persistence` returns a real bundle as of the
platform-authority port, and the same lifecycle is proven against a live
PostgreSQL server in `tests/postgres/test_hosted_boot.py`. The sentence is
corrected rather than deleted, because a stale scope note in a launch-gate test
is indistinguishable from a live limitation to whoever reads it next.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.providers.skool_lifecycle import SkoolLifecycleService
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.surface import CUSTOMER_SURFACE
from tests.hosted_helpers import create_testing_http_app
from tests.platform.admin_helpers import _seed_internal_admin
from tests.platform.provider_helpers import provider_config, seed_workspace
from tests.platform.test_authoritative_oauth import (
    REDIRECT,
    _live_http,
    _raw_initialized_session,
    _raw_mcp_request,
)


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
MCP_SCOPE = "mcp:tools"
TIER = "community_1:level_local"
MEMBER_ID = "member_private_beta_1"
REASON = {
    "reason_code": "entitlement_correction",
    "reason": "Verified against the internal Skool operations runbook.",
}

# One tool the Local Scout profile is entitled to, and one it is not. Both must
# be *real* names on the customer surface: asserting that an invented name is
# absent from tools/list passes no matter what the server does.
ENTITLED_TOOL = "cre_pipeline"
UNENTITLED_TOOL = "cre_offer"
LOCAL_SCOUT_TOOL_COUNT = 8


def _subject_id(path, workspace_row_id: int) -> int:
    with sqlite3.connect(path) as connection:
        return int(
            connection.execute(
                "SELECT user_id FROM platform_memberships WHERE workspace_id=?",
                (workspace_row_id,),
            ).fetchone()[0]
        )


def _skool_grant(path, workspace_row_id: int) -> tuple[str, str, str] | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            """
            SELECT status,profile,plan_key FROM platform_access_grants
            WHERE workspace_id=? AND source='skool'
            ORDER BY id DESC LIMIT 1
            """,
            (workspace_row_id,),
        ).fetchone()
    return (str(row[0]), str(row[1]), str(row[2])) if row is not None else None


def _confirmed_roster(member_id: str) -> dict:
    """A complete, confirmed operator review naming exactly this member."""
    return {
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
    }


async def test_skool_membership_grants_mcp_access_and_ending_it_denies_the_next_call(
    tmp_path,
):
    config = provider_config(
        tmp_path,
        skool_community_urls={"community_1": "https://www.skool.com/medawar-cre"},
    )
    repository = PlatformRepository(config.cache_db_path)

    # 1. Provision the test customer: workspace, member, and their territory.
    workspace = await seed_workspace(config, "Private Beta Member")
    customer_id = _subject_id(config.cache_db_path, workspace.id)
    territory = await repository.claim_territory(
        workspace.public_id,
        "TX territory",
        state="TX",
    )
    assert territory is not None

    # The operator is a separate human from the customer. Binding a Skool
    # member and revoking one are internal actions, never self-service.
    operator = await repository.create_user(
        "private-beta-operator@example.test",
        "Private Beta Operator",
    )
    assert operator is not None
    _seed_internal_admin(
        config.cache_db_path,
        user_id=operator.id,
        role="platform_admin",
        active=True,
    )
    service = SkoolLifecycleService(config)

    # 2. Skool entitlement. Joining is an audited operator task that binds the
    #    exact member id and deliberately grants nothing on its own.
    task = service.create_join_task(
        workspace.public_id,
        actor_user_id=operator.id,
        subject_user_id=customer_id,
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
    assert _skool_grant(config.cache_db_path, workspace.id) is None

    # Access arrives only from a complete, confirmed current-state review.
    reconciled = service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=operator.id,
        artifact=_confirmed_roster(MEMBER_ID),
        now=NOW,
        **REASON,
    )
    assert reconciled["certainty"] == "confirmed"
    assert _skool_grant(config.cache_db_path, workspace.id) == (
        "active",
        "local_scout",
        "local",
    )

    # 3. The Clerk-backed connection journey ends here: an OAuth session bound
    #    to the server-owned subject. The session takes no profile, plan, or
    #    territory input -- every one of those is re-derived from live state on
    #    each request -- so the only thing this token carries is identity and
    #    scope. The TTL is deliberately long so that a later denial cannot be
    #    explained away as expiry.
    auth = OAuthSessionStore(config.cache_db_path)
    client_record = auth.register_client("Claude", (REDIRECT,), (MCP_SCOPE,))
    tokens = auth.issue_session(
        workspace.public_id,
        customer_id,
        client_record.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    )
    token = tokens.access_token

    app = create_testing_http_app(config=config, skool_lifecycle_service=service)

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
            # Both names exist on the surface, so this pair distinguishes
            # "withheld from this profile" from "does not exist".
            assert UNENTITLED_TOOL in set(CUSTOMER_SURFACE.tools)
            assert UNENTITLED_TOOL not in names

            # 5. One allowed tool call succeeds.
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

            # 6. The unentitled tool is not merely hidden -- naming it directly
            #    is refused rather than executed.
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

            # 7. Membership ends. This is the manual revoke path, which is the
            #    only trustworthy removal signal Skool exposes today.
            report = service.manual_revoke(
                workspace.public_id,
                mapping_id,
                actor_user_id=operator.id,
                now=NOW,
                **REASON,
            )
            assert report["grant_status"] != "active"
            assert report["oauth_sessions_revoked"] >= 1

            # 8. The launch gate. The same token is still well inside its
            #    12-hour TTL, and the very next protected call is refused.
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

    # Asserted as the exact door, not merely "some refusal". Two independent
    # mechanisms deny here -- the session is revoked, and the grant is gone --
    # and a loose `in {401, 403}` cannot tell them apart: neutering the OAuth
    # session revocation still yields a 403 from the entitlement check, so the
    # loose form passes while the founder's actual requirement, that an
    # already-issued token stops authorizing, has silently regressed.
    assert after_revoke.status_code == 401, (
        "an ended Skool membership must invalidate the already-issued token "
        f"itself, not merely fail the entitlement check; got "
        f"{after_revoke.status_code}"
    )
    assert after_revoke.json()["error"] == "invalid_token"
