"""What migration 0012's identity projection does, and where it stops.

`medawarcre.project_platform_identity` closes the *identity* half of the hosted
admission gap: the platform authority keys identity with bigints, the certified
tenant schema keys it with uuids, and `PostgresAdmissionRepository.admit` parses
its actor and session as uuids. These tests pin that half -- idempotency, tenant
isolation, and the projected values matching what the caller read out of the
platform stores.

They also pin the half that is *not* closed, and the exact reason it cannot be
closed from inside this module. `medawarcre.atomic_admit_tool_call` (migration
0003) re-resolves the whole authority in SQL from a `credential` CTE over
`oauth_sessions`, `oauth_clients`, `access_grants`, `plans`, `territories` and
`workspace_accounts`. Nothing writes those rows, so admission returns
`authority_missing`. Projecting them needs the admission role to be able to
execute a call it cannot execute today, and `ADMISSION_FUNCTIONS` in
`cre_mcp/postgres/authority.py` is an exact-set pin that refuses both ways of
providing one. `test_extending_the_projection_needs_the_admission_pin_widened`
is that refusal, executed rather than asserted in prose.
"""

from __future__ import annotations

import psycopg
import pytest

from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_admission_object_authority,
)
from cre_mcp.postgres.identity_projection import (
    IdentityProjectionUnavailable,
    PlatformIdentityProjection,
    certified_role,
    user_uuid,
    workspace_uuid,
)
from cre_mcp.postgres.migrations import MigrationRunner

# The certified relations the `credential` CTE in migration 0003 reads, and
# which nothing in the product writes. `workspace_accounts` is easy to miss:
# the CTE LEFT JOINs it and the authority reason ladder turns a missing row
# into `account_missing`, so projecting the session and the grant without it
# still denies.
AUTHORITY_RELATIONS = (
    "oauth_clients",
    "oauth_sessions",
    "access_grants",
    "territories",
    "workspace_accounts",
)


def _admission_dsn(app_dsn: str) -> str:
    return app_dsn.replace("user=medawarcre_test_app", "user=medawarcre_test_admission")


@pytest.fixture
def migrated(postgres_database):
    """A migrated cluster, plus the superuser and admission DSNs for it."""
    superuser_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    return superuser_dsn, migration_dsn, _admission_dsn(app_dsn)


def _rows(dsn: str, statement: str, parameters=()):
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement, parameters).fetchall()


def _one(dsn: str, statement: str, parameters=()):
    rows = _rows(dsn, statement, parameters)
    return None if not rows else rows[0]


def _ensure(projection: PlatformIdentityProjection, **overrides):
    """Project one platform identity, with the shape `admit()` supplies."""
    payload = {
        "workspace_public_id": "ws_projection_alpha",
        "workspace_name": "Projection Alpha",
        "plan_key": "local",
        "platform_user_id": "41",
        "user_email": "platform-41@platform.medawarcre.invalid",
        "user_name": "platform-user-41",
        "role": "owner",
    }
    payload.update(overrides)
    return projection.ensure(**payload)


def test_projected_values_match_the_platform_source(migrated):
    superuser_dsn, _, admission_dsn = migrated
    projection = PlatformIdentityProjection(admission_dsn)

    resolved_workspace, resolved_user = _ensure(projection)

    assert resolved_workspace == workspace_uuid("ws_projection_alpha")
    assert resolved_user == user_uuid("41")

    workspace = _one(
        superuser_dsn,
        "SELECT public_id, name, state, plan_id FROM workspaces WHERE id=%s",
        (resolved_workspace,),
    )
    assert workspace[0] == "ws_projection_alpha"
    assert workspace[1] == "Projection Alpha"
    assert workspace[2] == "active"

    plan = _one(superuser_dsn, "SELECT id, plan_key FROM plans WHERE plan_key='local'")
    assert plan is not None
    assert workspace[3] == plan[0]

    user = _one(
        superuser_dsn,
        "SELECT email, name FROM users WHERE id=%s",
        (resolved_user,),
    )
    assert user == ("platform-41@platform.medawarcre.invalid", "platform-user-41")

    membership = _one(
        superuser_dsn,
        "SELECT role, state FROM memberships WHERE workspace_id=%s AND user_id=%s",
        (resolved_workspace, resolved_user),
    )
    assert membership == ("owner", "active")


def test_replaying_the_same_request_projects_nothing_new(migrated):
    """Idempotency: the same request twice is one row, not two, and no rotation."""
    superuser_dsn, _, admission_dsn = migrated
    projection = PlatformIdentityProjection(admission_dsn)

    first = _ensure(projection)
    before = _one(
        superuser_dsn,
        "SELECT w.id, w.public_id, w.name, w.plan_id, w.state, w.created_at, "
        "w.updated_at, m.id, m.role, m.state, u.email "
        "FROM workspaces w "
        "JOIN memberships m ON m.workspace_id = w.id "
        "JOIN users u ON u.id = m.user_id",
    )

    second = _ensure(projection)
    third = _ensure(projection)
    assert first == second == third

    after = _one(
        superuser_dsn,
        "SELECT w.id, w.public_id, w.name, w.plan_id, w.state, w.created_at, "
        "w.updated_at, m.id, m.role, m.state, u.email "
        "FROM workspaces w "
        "JOIN memberships m ON m.workspace_id = w.id "
        "JOIN users u ON u.id = m.user_id",
    )
    # Every column, including the surrogate membership id and both timestamps:
    # a projection that re-inserted, or that rotated an identifier, would show
    # up here even if the counts happened to stay right.
    assert after == before

    for relation in ("users", "workspaces", "memberships", "plans"):
        assert _one(superuser_dsn, f"SELECT count(*) FROM {relation}")[0] == 1


def test_two_platform_workspaces_stay_isolated(migrated):
    superuser_dsn, _, admission_dsn = migrated
    projection = PlatformIdentityProjection(admission_dsn)

    alpha_workspace, alpha_user = _ensure(projection)
    beta_workspace, beta_user = _ensure(
        projection,
        workspace_public_id="ws_projection_beta",
        workspace_name="Projection Beta",
        plan_key="national",
        platform_user_id="77",
        user_email="platform-77@platform.medawarcre.invalid",
        user_name="platform-user-77",
        role="member",
    )

    assert alpha_workspace != beta_workspace
    assert alpha_user != beta_user

    memberships = _rows(
        superuser_dsn,
        "SELECT workspace_id, user_id, role FROM memberships ORDER BY role",
    )
    assert memberships == [
        (beta_workspace, beta_user, "member"),
        (alpha_workspace, alpha_user, "owner"),
    ]

    # Neither workspace acquired the other's plan.
    assert _one(
        superuser_dsn,
        "SELECT p.plan_key FROM workspaces w JOIN plans p ON p.id=w.plan_id "
        "WHERE w.id=%s",
        (alpha_workspace,),
    ) == ("local",)
    assert _one(
        superuser_dsn,
        "SELECT p.plan_key FROM workspaces w JOIN plans p ON p.id=w.plan_id "
        "WHERE w.id=%s",
        (beta_workspace,),
    ) == ("national",)


def test_an_unmapped_role_is_refused_rather_than_widened(migrated):
    """Both halves refuse it: the Python map, and the function itself."""
    _, _, admission_dsn = migrated
    projection = PlatformIdentityProjection(admission_dsn)

    with pytest.raises(IdentityProjectionUnavailable):
        _ensure(projection, role="guest")
    with pytest.raises(IdentityProjectionUnavailable):
        certified_role("superuser")

    with psycopg.connect(admission_dsn) as connection:
        connection.execute("SET search_path TO pg_catalog")
        connection.execute("SET ROLE medawarcre_admission")
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "SELECT medawarcre.project_platform_identity("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    workspace_uuid("ws_projection_alpha"),
                    "ws_projection_alpha",
                    "Projection Alpha",
                    "local",
                    user_uuid("41"),
                    "platform-41@platform.medawarcre.invalid",
                    "platform-user-41",
                    "guest",
                ),
            )


def test_the_authority_half_of_the_projection_is_still_absent(migrated):
    """Identity projects; authority does not, and admission reads authority.

    This is the live statement of the remaining gap. After a successful
    projection the certified schema holds the user, workspace and membership
    the `credential` CTE joins -- and none of the five relations it also needs.
    """
    superuser_dsn, _, admission_dsn = migrated
    projection = PlatformIdentityProjection(admission_dsn)
    resolved_workspace, resolved_user = _ensure(projection)

    for relation in AUTHORITY_RELATIONS:
        assert _one(superuser_dsn, f"SELECT count(*) FROM {relation}")[0] == 0, (
            f"{relation} unexpectedly populated; if the authority projection "
            "has landed, this test and its docstring are stale"
        )

    # The identity half really is there, so the gap is authority and nothing
    # else -- not a missing user or a mis-derived uuid.
    assert _one(
        superuser_dsn,
        "SELECT count(*) FROM memberships WHERE workspace_id=%s AND user_id=%s "
        "AND state='active'",
        (resolved_workspace, resolved_user),
    ) == (1,)


def test_extending_the_projection_needs_the_admission_pin_widened(migrated):
    """The exact wall the authority projection hits.

    `ADMISSION_FUNCTIONS` in `cre_mcp/postgres/authority.py` is an exact set of
    (function name, argument types) that `medawarcre_admission` may execute, and
    `assert_admission_object_authority` compares the live catalog against it on
    *every* admission connection (`postgres/admission.py`), not only in tests.
    Both ways of giving the admission role the ability to project an oauth
    session, a grant, a territory and a workspace account are therefore refused
    until that set is edited:

      * a second SECURITY DEFINER function granted to the role, and
      * widening `project_platform_identity`'s own signature -- including with
        DEFAULTed parameters, because `pg_catalog.oidvectortypes(proargtypes)`
        reports the full argument vector regardless of defaults.

    Deleting this test to unblock the work would be deleting the review gate,
    which is what the pin exists to force.
    """
    _, migration_dsn, admission_dsn = migrated

    with psycopg.connect(admission_dsn) as connection:
        assert_admission_object_authority(connection)

    with psycopg.connect(migration_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "CREATE FUNCTION medawarcre.project_platform_authority("
            "p_workspace_id uuid, p_session_id uuid, p_expires_at timestamptz) "
            "RETURNS void LANGUAGE sql SECURITY DEFINER "
            "SET search_path = pg_catalog, medawarcre AS $$ SELECT $$"
        )
        connection.execute(
            "GRANT EXECUTE ON FUNCTION medawarcre.project_platform_authority("
            "uuid, uuid, timestamptz) TO medawarcre_admission"
        )
        connection.commit()

    with psycopg.connect(admission_dsn) as connection:
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_admission_object_authority(connection)

    with psycopg.connect(migration_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "DROP FUNCTION medawarcre.project_platform_authority("
            "uuid, uuid, timestamptz)"
        )
        connection.execute(
            "CREATE FUNCTION medawarcre.project_platform_identity("
            "p_workspace_id uuid, p_workspace_public_id text, "
            "p_workspace_name text, p_plan_key text, p_user_id uuid, "
            "p_user_email text, p_user_name text, p_role text, "
            "p_session_id uuid DEFAULT NULL) "
            "RETURNS uuid LANGUAGE sql SECURITY DEFINER "
            "SET search_path = pg_catalog, medawarcre "
            "AS $$ SELECT p_workspace_id $$"
        )
        connection.execute(
            "GRANT EXECUTE ON FUNCTION medawarcre.project_platform_identity("
            "uuid, text, text, text, uuid, text, text, text, uuid) "
            "TO medawarcre_admission"
        )
        connection.commit()

    with psycopg.connect(admission_dsn) as connection:
        connection.execute("SET search_path TO pg_catalog")
        signatures = {
            row[0]
            for row in connection.execute(
                "SELECT p.proname || '|' || "
                "pg_catalog.oidvectortypes(p.proargtypes) "
                "FROM pg_catalog.pg_proc p "
                "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname='medawarcre' "
                "AND p.proname='project_platform_identity'"
            ).fetchall()
        }
        assert signatures == {
            "project_platform_identity|uuid, text, text, text, uuid, text, text, text",
            "project_platform_identity|uuid, text, text, text, uuid, text, text, "
            "text, uuid",
        }
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_admission_object_authority(connection)
