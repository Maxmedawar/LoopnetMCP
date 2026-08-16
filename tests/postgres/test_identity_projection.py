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


# --- the four edges a confirmatory review found in the 0013 repair -----------


def test_reassigning_an_email_does_not_lock_the_new_holder_out(projection) -> None:
    """0013 narrowed the users arbiter to (id) and set the email unconditionally.

    `medawarcre.users` also has a case-folded unique index on email, so the
    supported sequence -- rename A off an address, give B that address -- made
    every one of B's requests raise UniqueViolation until A happened to project
    first. Fail-closed, and a total lockout.
    """
    desk, owner_dsn = projection
    _wa, user_a = _seed_platform(owner_dsn, "ws_email_a", "Email A")
    _wb, user_b = _seed_platform(owner_dsn, "ws_email_b", "Email B")
    desk.ensure(workspace_public_id="ws_email_a", platform_user_id=user_a)
    desk.ensure(workspace_public_id="ws_email_b", platform_user_id=user_b)

    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "UPDATE platform_users SET email='moved-away@example.test' WHERE id=%s",
            (user_a,),
        )
        connection.execute(
            "UPDATE platform_users SET email='ws_email_a@example.test' WHERE id=%s",
            (user_b,),
        )
        connection.commit()

    # B must still be able to project. Their certified email may lag; that is a
    # cosmetic divergence, where a lockout is an outage.
    assert desk.ensure(
        workspace_public_id="ws_email_b", platform_user_id=user_b
    )[1] == user_uuid(str(user_b))


def test_a_concurrent_cold_start_does_not_violate_the_primary_key(
    projection,
) -> None:
    """0013's workspace arbiter named (public_id); the derived id collides first.

    On two simultaneous first requests for a new workspace the primary key
    conflict is reached before the ON CONFLICT clause applies, so one caller got
    UniqueViolation. It reproduced on the first of eight concurrent rounds --
    cold-start only, and on the launch path.
    """
    import concurrent.futures

    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_cold", "Cold Tenant")

    def project():
        return desk.ensure(workspace_public_id="ws_cold", platform_user_id=user)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = [future.result() for future in
                   [pool.submit(project) for _ in range(8)]]
    assert len({result[0] for result in results}) == 1
    assert _owner(owner_dsn, "SELECT count(*) FROM workspaces") == [(1,)]


def test_an_unparseable_timestamp_denies_rather_than_breaking_the_relation(
    projection,
) -> None:
    """The platform timestamps are text; 0013 cast them straight through.

    An unparseable value turned every request into an outage. Worse, a value
    that parses but predates year 1 was written into the certified table, after
    which every psycopg read of `medawarcre.oauth_sessions` raised `timestamp
    too small` -- one bad row and the relation becomes unreadable.
    """
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_clock", "Clock Tenant")
    workspace_id, user_id = desk.ensure(
        workspace_public_id="ws_clock", platform_user_id=user
    )
    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_oauth_clients"
            "(client_id,name,redirect_uris,scopes,active,created_at,updated_at) "
            "VALUES ('c_clock','Clock','[]','[]',1,'2026-01-01','2026-01-01')"
        )
        connection.execute(
            "INSERT INTO platform_accounts(workspace_id,state,updated_at) "
            "SELECT id,'active','2026-01-01' FROM platform_workspaces "
            "WHERE public_id='ws_clock'"
        )
        connection.execute(
            "INSERT INTO platform_oauth_sessions("
            "session_id,workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at,revoked_at,"
            "created_at,updated_at) VALUES "
            "('sess_clock','ws_clock',%s,'c_clock','[]','a','r',1,'h1','h2',"
            "'0001-01-01 BC','2027-01-01','2027-01-01','0001-01-01 BC',"
            "'2026-01-01','2026-01-01')",
            (user,),
        )
        connection.commit()

    desk.ensure_authority(
        workspace_id=workspace_id,
        workspace_public_id="ws_clock",
        user_id=user_id,
        platform_user_id=user,
        session_id=session_uuid("sess_clock"),
        platform_session_id="sess_clock",
        audience="medawarcre-mcp",
        resource="https://mcp.medawarcre.com/mcp",
    )
    # The relation is still readable, which is the property that matters.
    expires, revoked = _owner(
        owner_dsn, "SELECT access_expires_at, revoked_at FROM oauth_sessions"
    )[0]
    assert expires.year >= 1900
    assert revoked is not None and revoked.year >= 1900


def test_territory_positions_are_corrected_when_the_set_changes(
    projection,
) -> None:
    """Positions are baked into the id, and 0013 never rewrote an existing one.

    Admission rebuilds the array ordered by `min(territory.id::text)`, so a
    stale position permanently disagrees with the resolver's order and the
    workspace is denied on every retry. Remove one territory, add another, and
    the ids must renumber.
    """
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_terr", "Territory Tenant")
    workspace_id, user_id = desk.ensure(
        workspace_public_id="ws_terr", platform_user_id=user
    )

    def platform_territories(values):
        with psycopg.connect(owner_dsn) as connection:
            connection.execute("SET search_path TO medawarcre, pg_catalog")
            connection.execute(
                "DELETE FROM platform_territories WHERE workspace_id="
                "(SELECT id FROM platform_workspaces WHERE public_id='ws_terr')"
            )
            for name, state in values:
                connection.execute(
                    "INSERT INTO platform_territories"
                    "(workspace_id,name,state,created_at,updated_at) SELECT id,"
                    "%s,%s,'2026-01-01','2026-01-01' FROM platform_workspaces "
                    "WHERE public_id='ws_terr'",
                    (name, state),
                )
            connection.commit()

    def project_and_read():
        with psycopg.connect(owner_dsn) as connection:
            connection.execute("SET search_path TO medawarcre, pg_catalog")
            connection.execute(
                "INSERT INTO platform_accounts(workspace_id,state,updated_at) "
                "SELECT id,'active','2026-01-01' FROM platform_workspaces "
                "WHERE public_id='ws_terr' ON CONFLICT DO NOTHING"
            )
            connection.execute(
                "INSERT INTO platform_oauth_clients"
                "(client_id,name,redirect_uris,scopes,active,created_at,updated_at) "
                "VALUES ('c_terr','T','[]','[]',1,'2026-01-01','2026-01-01') "
                "ON CONFLICT DO NOTHING"
            )
            connection.execute(
                "INSERT INTO platform_oauth_sessions("
                "session_id,workspace_id,user_id,client_id,scopes,audience,"
                "resource,authority_version,access_hash,refresh_hash,"
                "access_expires_at,refresh_expires_at,refresh_family_expires_at,"
                "created_at,updated_at) VALUES ('sess_terr','ws_terr',%s,'c_terr',"
                "'[]','a','r',1,'h1','h2','2027-01-01','2027-01-01','2027-01-01',"
                "'2026-01-01','2026-01-01') ON CONFLICT DO NOTHING",
                (user,),
            )
            connection.commit()
        desk.ensure_authority(
            workspace_id=workspace_id,
            workspace_public_id="ws_terr",
            user_id=user_id,
            platform_user_id=user,
            session_id=session_uuid("sess_terr"),
            platform_session_id="sess_terr",
            audience="medawarcre-mcp",
            resource="https://mcp.medawarcre.com/mcp",
        )
        return [
            row[0]
            for row in _owner(
                owner_dsn,
                "SELECT name FROM territories WHERE workspace_id=%s "
                "ORDER BY id::text",
                (workspace_id,),
            )
        ]

    platform_territories([("Texas", "TX"), ("New York", "NY"), ("Cal", "CA")])
    assert project_and_read() == ["TX", "NY", "CA"]

    # Remove the first, add a new last. Under 0013 the surviving ids kept their
    # old positions and the new one landed in the middle of the text order.
    platform_territories([("New York", "NY"), ("Cal", "CA"), ("Florida", "FL")])
    assert project_and_read() == ["NY", "CA", "FL"]


def test_an_empty_state_falls_through_the_way_the_resolver_does(
    projection,
) -> None:
    """`COALESCE` returns an empty string; Python's `or` falls past it.

    `AuthorityResolver` computes `row["state"] or row["market"] or row["name"]`.
    The projection used `COALESCE(state, market, name)`, and `''` is not NULL --
    so it won, was dropped by the non-empty filter, and the two sets diverged
    into a permanent `authority_changed` denial.
    """
    desk, owner_dsn = projection
    _workspace, user = _seed_platform(owner_dsn, "ws_blank", "Blank Tenant")
    workspace_id, user_id = desk.ensure(
        workspace_public_id="ws_blank", platform_user_id=user
    )
    with psycopg.connect(owner_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_territories"
            "(workspace_id,name,state,market,created_at,updated_at) SELECT id,"
            "'Dallas Metro','','Dallas','2026-01-01','2026-01-01' "
            "FROM platform_workspaces WHERE public_id='ws_blank'"
        )
        connection.execute(
            "INSERT INTO platform_accounts(workspace_id,state,updated_at) "
            "SELECT id,'active','2026-01-01' FROM platform_workspaces "
            "WHERE public_id='ws_blank'"
        )
        connection.execute(
            "INSERT INTO platform_oauth_clients"
            "(client_id,name,redirect_uris,scopes,active,created_at,updated_at) "
            "VALUES ('c_blank','B','[]','[]',1,'2026-01-01','2026-01-01')"
        )
        connection.execute(
            "INSERT INTO platform_oauth_sessions("
            "session_id,workspace_id,user_id,client_id,scopes,audience,resource,"
            "authority_version,access_hash,refresh_hash,access_expires_at,"
            "refresh_expires_at,refresh_family_expires_at,created_at,updated_at) "
            "VALUES ('sess_blank','ws_blank',%s,'c_blank','[]','a','r',1,'h1','h2',"
            "'2027-01-01','2027-01-01','2027-01-01','2026-01-01','2026-01-01')",
            (user,),
        )
        connection.commit()

    desk.ensure_authority(
        workspace_id=workspace_id,
        workspace_public_id="ws_blank",
        user_id=user_id,
        platform_user_id=user,
        session_id=session_uuid("sess_blank"),
        platform_session_id="sess_blank",
        audience="medawarcre-mcp",
        resource="https://mcp.medawarcre.com/mcp",
    )
    # 'Dallas', the market — the same value the resolver produces.
    assert _owner(owner_dsn, "SELECT name FROM territories") == [("Dallas",)]
