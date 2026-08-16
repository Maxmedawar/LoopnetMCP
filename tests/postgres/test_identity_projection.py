"""The mechanics of the identity projection: derivation, idempotency, refusal.

The security properties live next door in `test_projection_is_a_projection.py`,
which pins the four defects an independent review found in migration 0012. This
file covers the parts that are true regardless of those: that the derived
identifiers are stable and idempotent, that two platform workspaces stay
distinct, and that a projection with nothing to copy refuses rather than
inventing.

This file previously tested migration 0012's API, which accepted the projected
values as arguments, and its last test pinned "extending this needs the
admission pin widened" as a blocker. Both are gone: 0013 replaced the functions
so they read the platform relations, and the pin was widened deliberately with
its reasoning recorded in `postgres/authority.py`.
"""

from __future__ import annotations

import psycopg
import pytest

from cre_mcp.platform.projected_ids import (
    IDENTITY_NAMESPACE,
    ProjectedIdentityError,
    session_uuid,
    user_uuid,
    workspace_uuid,
)
from cre_mcp.postgres.identity_projection import (
    IdentityProjectionUnavailable,
    PlatformIdentityProjection,
)
from cre_mcp.postgres.migrations import MigrationRunner


@pytest.fixture
def projection(postgres_database):
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    admission_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admission"
    )
    owner_dsn = app_dsn.replace("user=medawarcre_test_app", "user=postgres")
    return PlatformIdentityProjection(admission_dsn), owner_dsn


def _owner(owner_dsn: str, statement: str, parameters=()):
    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        result = connection.execute(statement, parameters).fetchall()
        connection.commit()
        return result


def _seed_platform(owner_dsn: str, public_id: str, name: str) -> tuple[int, int]:
    """One platform workspace, user and membership — the projection's source."""
    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        plan = connection.execute(
            "INSERT INTO platform_plans(key,name,created_at,updated_at) "
            "VALUES (%s,%s,'2026-01-01','2026-01-01') "
            "ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            ("local", "Local"),
        ).fetchone()[0]
        workspace = connection.execute(
            "INSERT INTO platform_workspaces(public_id,name,plan_id,created_at,"
            "updated_at) VALUES (%s,%s,%s,'2026-01-01','2026-01-01') RETURNING id",
            (public_id, name, plan),
        ).fetchone()[0]
        user = connection.execute(
            "INSERT INTO platform_users(email,name,created_at,updated_at) "
            "VALUES (%s,%s,'2026-01-01','2026-01-01') RETURNING id",
            (f"{public_id}@example.test", f"{name} Member"),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO platform_memberships(workspace_id,user_id,role,"
            "created_at,updated_at) VALUES (%s,%s,'member','2026-01-01',"
            "'2026-01-01')",
            (workspace, user),
        )
        connection.commit()
    return workspace, user


# --- derivation --------------------------------------------------------------


def test_the_derived_identifiers_are_stable_and_namespaced() -> None:
    assert workspace_uuid("ws_alpha") == workspace_uuid("ws_alpha")
    assert workspace_uuid("ws_alpha") != workspace_uuid("ws_beta")
    assert user_uuid("41") != session_uuid("41")
    assert str(IDENTITY_NAMESPACE)


def test_derivation_is_idempotent_on_an_already_derived_value() -> None:
    """The context is built once and read many times.

    A second application would silently produce a different tenant, so a value
    that is already a uuid comes back unchanged.
    """
    once = user_uuid("41")
    assert user_uuid(once) == once
    assert user_uuid(str(once)) == once
    assert session_uuid(session_uuid("sess_x")) == session_uuid("sess_x")


def test_an_empty_identifier_is_refused() -> None:
    for call in (workspace_uuid, user_uuid, session_uuid):
        with pytest.raises(ProjectedIdentityError):
            call("   ")


# --- projection --------------------------------------------------------------


def test_the_projection_copies_the_platform_row(projection) -> None:
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_copy", "Copy Tenant")

    workspace_id, user_id = desk.ensure(
        workspace_public_id="ws_copy", platform_user_id=user
    )
    assert workspace_id == workspace_uuid("ws_copy")
    assert user_id == user_uuid(str(user))

    assert _owner(
        owner_dsn, "SELECT public_id, name, state FROM workspaces"
    ) == [("ws_copy", "Copy Tenant", "active")]
    assert _owner(owner_dsn, "SELECT email FROM users") == [
        ("ws_copy@example.test",)
    ]
    # The platform's own role, not a fabricated 'owner'.
    assert _owner(owner_dsn, "SELECT role, state FROM memberships") == [
        ("member", "active")
    ]


def test_projecting_twice_changes_nothing(projection) -> None:
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_twice", "Twice Tenant")

    first = desk.ensure(workspace_public_id="ws_twice", platform_user_id=user)
    before = _owner(owner_dsn, "SELECT id, public_id FROM workspaces")
    for _ in range(2):
        assert desk.ensure(
            workspace_public_id="ws_twice", platform_user_id=user
        ) == first
    assert _owner(owner_dsn, "SELECT id, public_id FROM workspaces") == before
    for table in ("users", "workspaces", "memberships"):
        assert _owner(owner_dsn, f"SELECT count(*) FROM {table}") == [(1,)]


def test_two_platform_workspaces_stay_distinct(projection) -> None:
    desk, owner_dsn = projection
    _a, user_a = _seed_platform(owner_dsn, "ws_one", "One Tenant")
    _b, user_b = _seed_platform(owner_dsn, "ws_two", "Two Tenant")

    one = desk.ensure(workspace_public_id="ws_one", platform_user_id=user_a)
    two = desk.ensure(workspace_public_id="ws_two", platform_user_id=user_b)
    assert one[0] != two[0]
    assert one[1] != two[1]
    assert sorted(
        row[0] for row in _owner(owner_dsn, "SELECT public_id FROM workspaces")
    ) == ["ws_one", "ws_two"]
    assert _owner(owner_dsn, "SELECT count(*) FROM memberships") == [(2,)]


def test_a_workspace_the_platform_does_not_hold_is_refused(projection) -> None:
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_real", "Real Tenant")

    with pytest.raises(IdentityProjectionUnavailable):
        desk.ensure(workspace_public_id="ws_absent", platform_user_id=user)
    assert _owner(
        owner_dsn, "SELECT count(*) FROM workspaces WHERE public_id='ws_absent'"
    ) == [(0,)]


def test_a_user_who_is_not_a_member_is_refused(projection) -> None:
    """Membership is the authorization fact, not a formality."""
    desk, owner_dsn = projection
    _workspace, member = _seed_platform(owner_dsn, "ws_member", "Member Tenant")
    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        stranger = connection.execute(
            "INSERT INTO platform_users(email,name,created_at,updated_at) "
            "VALUES ('stranger@example.test','Stranger','2026-01-01',"
            "'2026-01-01') RETURNING id"
        ).fetchone()[0]
        connection.commit()

    with pytest.raises(IdentityProjectionUnavailable):
        desk.ensure(workspace_public_id="ws_member", platform_user_id=stranger)
    # And nothing partial survives: no certified user row for the stranger.
    assert _owner(
        owner_dsn,
        "SELECT count(*) FROM users WHERE email='stranger@example.test'",
    ) == [(0,)]
