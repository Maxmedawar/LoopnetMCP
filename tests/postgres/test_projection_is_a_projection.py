"""What migration 0013 fixed, each defect pinned by the failure it caused.

An independent review of migration 0012 confirmed four defects with running
probes. Every test here is one of them, written so that reverting 0013 turns it
red rather than so that it describes the repair.

The common cause was that 0012's projection accepted the values it wrote as
arguments. It validated their shape and never checked that any of them existed
in the platform authority, so it was an echo of its caller rather than a copy of
stored state -- while its own header claimed it "can only insert rows that
already exist in the platform authority".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from cre_mcp.access.context import TenantContext
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.postgres.identity_projection import IdentityProjectionUnavailable
from tests.postgres.test_skool_launch_gate import (  # noqa: F401
    MCP_SCOPE,
    NOW,
    REASON,
    TIER,
    _confirmed_roster,
    _owner_one,
    hosted_app,
)

MEMBER_ID = "member_projection_fix"


def _owner(dsn: str) -> str:
    return dsn.replace("user=medawarcre_test_app", "user=postgres")


async def _entitled_customer(bundle, config, dsn):
    """One real Skool-entitled customer, provisioned the supported way."""
    repository = PlatformRepository(config=config)
    service = bundle.platform_api.skool_lifecycle
    for key in ("local", "national", "operator", "jv"):
        if not any(item.key == key for item in await repository.list_plans()):
            await repository.create_plan(key, key.title())
    workspace = await repository.create_workspace("Projection Tenant")
    customer = await repository.create_user(
        "projection-customer@example.test", "Projection Customer"
    )
    await repository.add_membership(workspace.public_id, customer.id, "member")
    await repository.claim_territory(
        workspace.public_id, "TX territory", state="TX"
    )
    operator = await repository.create_user(
        "projection-operator@example.test", "Projection Operator"
    )
    with psycopg.connect(_owner(dsn)) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_internal_admins"
            "(user_id, role, active, created_at, updated_at) "
            "VALUES (%s,'platform_admin',1,%s,%s)",
            (operator.id, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
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
    service.reconcile_workspace(
        workspace.public_id,
        actor_user_id=operator.id,
        artifact=_confirmed_roster(MEMBER_ID),
        now=NOW,
        **REASON,
    )
    return workspace, customer, operator, int(
        completed["task"]["external_mapping_id"]
    ), service


def _admit(bundle, context):
    return bundle.admission_repository.admit(
        context,
        "cre_pipeline",
        {"action": "list_searches"},
        quota_bucket="search",
        requires_approval=False,
    )


def _context(workspace_public_id, actor_uuid, session_uuid, platform_actor,
             platform_session, *, profile="local_scout", plan="local",
             territories=("TX",), quota_limits=None) -> TenantContext:
    return TenantContext(
        workspace_id=workspace_public_id,
        profile=profile,
        plan=plan,
        quota_limits=quota_limits or {"search": 100},
        territories=territories,
        active=True,
        trusted=False,
        display_name="Projection Tenant",
        actor_id=str(actor_uuid),
        session_id=str(session_uuid),
        platform_actor_id=str(platform_actor),
        platform_session_id=str(platform_session),
    )


async def test_a_workspace_the_platform_authority_does_not_hold_is_refused(
    hosted_app,
):
    """The review's probe, turned into a test.

    Under 0012 this exact call returned `decision='allowed'` and left
    `ws_fabricated_by_caller` in `medawarcre.workspaces` with a `full_operator`
    grant and a 999999 quota.
    """
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence
    from cre_mcp.platform.projected_ids import session_uuid, user_uuid

    fabricated = _context(
        "ws_fabricated_by_caller",
        user_uuid("4242"),
        session_uuid("sess_fabricated"),
        "4242",
        "sess_fabricated",
        profile="full_operator",
        plan="operator",
        territories=("CA", "TX", "NY"),
        quota_limits={"search": 999999},
    )
    with pytest.raises(IdentityProjectionUnavailable):
        _admit(bundle, fabricated)

    assert _owner_one(
        dsn,
        "SELECT count(*) FROM workspaces WHERE public_id=%s",
        ("ws_fabricated_by_caller",),
    )[0] == 0
    assert _owner_one(
        dsn, "SELECT count(*) FROM access_grants WHERE profile='full_operator'"
    )[0] == 0


async def test_the_caller_cannot_choose_the_profile_plan_or_quota(hosted_app):
    """A real workspace, an inflated claim: the stored grant wins."""
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence
    from cre_mcp.platform.projected_ids import session_uuid, user_uuid

    workspace, customer, _operator, _mapping, _service = await _entitled_customer(
        bundle, config, dsn
    )
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client("Projection Client", ("https://x.test/cb",), (MCP_SCOPE,))
    tokens = auth.issue_session(
        workspace.public_id,
        customer.id,
        client.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    )
    session_row = auth.validate_access(tokens.access_token)

    overclaimed = _context(
        workspace.public_id,
        user_uuid(str(customer.id)),
        session_uuid(session_row.session_id),
        customer.id,
        session_row.session_id,
        profile="full_operator",
        plan="operator",
        quota_limits={"search": 999999},
    )
    outcome = _admit(bundle, overclaimed)
    # Admission compares the projected authority against the caller's claim, so
    # an inflated claim is a mismatch rather than a promotion.
    assert outcome.decision == "denied"
    assert _owner_one(
        dsn,
        "SELECT profile, plan_key FROM access_grants WHERE source='manual' "
        "ORDER BY updated_at DESC LIMIT 1",
    ) == ("local_scout", "local")

    # And the membership role is the platform's, not a fabricated 'owner'.
    # 0012 wrote `"owner" if profile else "member"`, so every hosted user became
    # an owner of their workspace in the certified schema.
    assert _owner_one(dsn, "SELECT role FROM memberships LIMIT 1") == ("member",)


async def test_ending_a_skool_membership_revokes_the_projected_grant(hosted_app):
    """The finding that broke the launch gate through the back door.

    Nothing but the projection writes `medawarcre.access_grants`, and 0012 wrote
    `status='active', ends_at=NULL` from the caller's profile. So after a
    `manual_revoke` the projected grant stayed active forever, and
    `SavedSearchScheduler`'s documented "live entitlement recheck" -- which
    reads that row, not the platform one -- kept returning an entitlement for a
    revoked member. The worker would run their saved searches indefinitely.
    """
    app, config, dsn = hosted_app
    bundle = app.state.hosted_persistence
    from cre_mcp.platform.projected_ids import session_uuid, user_uuid

    workspace, customer, operator, mapping_id, service = await _entitled_customer(
        bundle, config, dsn
    )
    auth = OAuthSessionStore(config.cache_db_path)
    client = auth.register_client("Revoke Client", ("https://x.test/cb",), (MCP_SCOPE,))
    tokens = auth.issue_session(
        workspace.public_id,
        customer.id,
        client.client_id,
        scopes=(MCP_SCOPE,),
        access_ttl=timedelta(hours=12),
    )
    session_row = auth.validate_access(tokens.access_token)
    context = _context(
        workspace.public_id,
        user_uuid(str(customer.id)),
        session_uuid(session_row.session_id),
        customer.id,
        session_row.session_id,
    )
    assert _admit(bundle, context).decision == "allowed"
    assert _owner_one(
        dsn, "SELECT status FROM access_grants WHERE source='manual'"
    ) == ("active",)

    report = service.manual_revoke(
        workspace.public_id,
        mapping_id,
        actor_user_id=operator.id,
        now=datetime.now(UTC),
        **REASON,
    )
    assert report["grant_status"] != "active"

    # The next projection -- which is what any worker or request triggers --
    # must carry the revocation across. Under 0012 this stayed ('active', None).
    # Admission denies rather than raising: the projection succeeds (it copies
    # the revocation) and the credential CTE then finds no live grant.
    after = _admit(bundle, context)
    assert after.decision == "denied"
    status, ends_at = _owner_one(
        dsn, "SELECT status, ends_at FROM access_grants WHERE source='manual'"
    )
    assert status == "revoked" or (ends_at is not None and ends_at <= datetime.now(UTC))

    # And the projected session carries the revocation rather than being
    # un-revoked. 0012 set `revoked_at = NULL` unconditionally on every upsert.
    revoked_at = _owner_one(dsn, "SELECT revoked_at FROM oauth_sessions LIMIT 1")
    assert revoked_at is None or revoked_at[0] is not None


async def test_the_customer_role_cannot_make_itself_a_platform_admin(hosted_app):
    """The privilege escalation the review confirmed.

    `medawarcre_app` is the customer-serving role. It could write itself a
    `platform_internal_admins` row and become the exact identity
    `AdminControlStore._mutate` checks before permitting workspace, grant and
    territory mutation. No store writes that table on a request path, so
    revoking write costs nothing.
    """
    _app, _config, dsn = hosted_app
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO platform_internal_admins"
                "(user_id, role, active, created_at, updated_at) "
                "VALUES (1,'platform_admin',1,'2026-01-01','2026-01-01')"
            )
        connection.rollback()
        # `SET search_path` is transactional, and the rollback above took it
        # with the aborted statement, so it is set again rather than assumed.
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        # Reading it is still allowed -- AuthorityResolver checks it on every
        # request -- so this is the narrowest revoke that closes the door.
        assert connection.execute(
            "SELECT count(*) FROM platform_internal_admins"
        ).fetchone() is not None
