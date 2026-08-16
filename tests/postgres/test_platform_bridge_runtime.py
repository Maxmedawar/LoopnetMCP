"""The platform authority stores, running against a real PostgreSQL server.

The translation tests next door prove the dialect rules in isolation. These
prove the thing that actually matters: the twelve stores the hosted process
depends on do their real work — create a tenant, register a client, issue and
validate a session, resolve live authority, take an audited admin mutation —
with no SQLite file anywhere, against a database that enforces the grants in
migration 0010.

Everything here runs as ``medawarcre_test_app``, a login whose only privileges
are the ones the migration grants the application role. A test that passed as a
superuser would prove nothing about production.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import AdminControlStore
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.authority import AuthorityResolver
from cre_mcp.platform.dbapi import (
    PlatformBackendConflict,
    clear_platform_backend,
    current_platform_backend,
    install_platform_backend,
    platform_backend_is_remote,
)
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.postgres.access_audit import PostgresAccessAuditLog
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.platform_bridge import (
    PostgresPlatformBackend,
    UnsafePlatformRoleError,
)

#: A path that must never come into existence while the backend is installed.
UNUSED_DB = "platform-authority-must-not-touch-this.sqlite3"


@pytest.fixture
def platform_backend(postgres_database, tmp_path: Path):
    """A migrated database with the PostgreSQL platform backend installed."""
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    backend = PostgresPlatformBackend(app_dsn, min_size=1, max_size=4)
    backend.open(wait=True)
    install_platform_backend(backend)
    try:
        yield backend, app_dsn, tmp_path / UNUSED_DB
    finally:
        clear_platform_backend()
        backend.close()


def _config(db_path: Path) -> CreConfig:
    return CreConfig(cache_db_path=str(db_path))


def _rows(dsn: str, statement: str, parameters=()) -> list[tuple]:
    with psycopg.connect(dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        return connection.execute(statement, parameters).fetchall()


# --- the seam itself ---------------------------------------------------------


def test_no_backend_installed_is_the_default(tmp_path: Path) -> None:
    assert current_platform_backend() is None
    assert platform_backend_is_remote() is False


def test_installing_a_second_different_backend_is_refused(
    platform_backend,
) -> None:
    backend, app_dsn, _ = platform_backend
    install_platform_backend(backend)  # idempotent for the same object
    other = PostgresPlatformBackend(app_dsn)
    with pytest.raises(PlatformBackendConflict):
        install_platform_backend(other)


def test_a_dsn_that_exceeds_the_application_role_is_refused(
    postgres_database,
) -> None:
    superuser_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn).apply()
    backend = PostgresPlatformBackend(superuser_dsn)
    with pytest.raises(UnsafePlatformRoleError):
        backend.open(wait=True)
    backend.close()


# --- the stores, doing real work --------------------------------------------


def test_a_tenant_is_created_in_postgresql_and_no_sqlite_file_appears(
    platform_backend,
) -> None:
    _, app_dsn, unused = platform_backend
    repository = PlatformRepository(config=_config(unused))

    async def scenario():
        user = await repository.create_user("Owner@Example.COM", "Owner")
        workspace = await repository.create_workspace("Launch Tenant")
        membership = await repository.add_membership(
            workspace.public_id, user.id, "owner"
        )
        return user, workspace, membership

    user, workspace, membership = asyncio.run(scenario())

    assert user.email == "owner@example.com"
    assert workspace.public_id.startswith("ws_")
    assert membership.role == "owner"

    stored = _rows(
        app_dsn,
        "SELECT email, name FROM platform_users WHERE id=%s",
        (user.id,),
    )
    assert stored == [("owner@example.com", "Owner")]
    assert _rows(
        app_dsn,
        "SELECT role FROM platform_memberships "
        "WHERE workspace_id=%s AND user_id=%s",
        (workspace.id, user.id),
    ) == [("owner",)]

    # The whole point of the port: the authority is not in a file.
    assert not unused.exists()


def test_a_duplicate_email_still_reports_a_conflict_not_a_crash(
    platform_backend,
) -> None:
    _, _, unused = platform_backend
    repository = PlatformRepository(config=_config(unused))

    async def scenario():
        first = await repository.create_user("dup@example.com", "First")
        second = await repository.create_user("dup@example.com", "Second")
        return first, second

    first, second = asyncio.run(scenario())
    # PlatformRepository._run turns sqlite3.IntegrityError into None. The bridge
    # has to raise that exact class for this contract to survive the port.
    assert first is not None
    assert second is None


def test_an_issued_session_validates_and_resolves_live_authority(
    platform_backend,
) -> None:
    _, app_dsn, unused = platform_backend
    config = _config(unused)
    repository = PlatformRepository(config=config)
    oauth = OAuthSessionStore(unused)

    async def scenario():
        user = await repository.create_user("member@example.com", "Member")
        workspace = await repository.create_workspace("Session Tenant")
        await repository.add_membership(workspace.public_id, user.id, "owner")
        return user, workspace

    user, workspace = asyncio.run(scenario())

    client = oauth.register_public_client(
        "Test Client", ("https://example.com/callback",), ("mcp:invoke",)
    )
    tokens = oauth.issue_session(
        workspace.public_id,
        user.id,
        client.client_id,
        access_ttl=timedelta(minutes=15),
    )

    session = oauth.validate_access(tokens.access_token)
    assert session is not None
    assert session.workspace_id == workspace.public_id
    assert session.user_id == user.id

    resolver = AuthorityResolver(unused)
    outcome = resolver.resolve(tokens.access_token)
    assert outcome is not None
    assert outcome.session.workspace_id == workspace.public_id

    # The session is a row in PostgreSQL, not a file.
    assert _rows(
        app_dsn,
        "SELECT count(*) FROM platform_oauth_sessions WHERE workspace_id=%s",
        (workspace.public_id,),
    ) == [(1,)]
    assert not unused.exists()


def test_a_revoked_session_stops_validating_immediately(
    platform_backend,
) -> None:
    _, _, unused = platform_backend
    repository = PlatformRepository(config=_config(unused))
    oauth = OAuthSessionStore(unused)

    async def scenario():
        user = await repository.create_user("revoke@example.com", "Revoke")
        workspace = await repository.create_workspace("Revoke Tenant")
        await repository.add_membership(workspace.public_id, user.id, "owner")
        return user, workspace

    user, workspace = asyncio.run(scenario())
    client = oauth.register_public_client(
        "Revoke Client", ("https://example.com/callback",), ("mcp:invoke",)
    )
    tokens = oauth.issue_session(workspace.public_id, user.id, client.client_id)

    assert oauth.validate_access(tokens.access_token) is not None
    assert oauth.revoke_token(tokens.access_token) is True
    # Not "eventually", and not at expiry: the very next validation.
    assert oauth.validate_access(tokens.access_token) is None


def test_an_admin_mutation_writes_its_audit_row_in_the_same_transaction(
    platform_backend,
) -> None:
    _, app_dsn, unused = platform_backend
    repository = PlatformRepository(config=_config(unused))
    admin = AdminControlStore(unused)

    async def scenario():
        operator = await repository.create_user("ops@example.com", "Ops")
        subject = await repository.create_user("sub@example.com", "Subject")
        workspace = await repository.create_workspace("Audited Tenant")
        await repository.add_membership(workspace.public_id, subject.id, "owner")
        return operator, workspace

    operator, workspace = asyncio.run(scenario())

    # Seeded as the cluster owner: migration 0013 revoked the application
    # role's write on this table, because it could otherwise make itself the
    # exact identity AdminControlStore._mutate checks.
    with psycopg.connect(
        app_dsn.replace("user=medawarcre_test_app", "user=postgres")
    ) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        connection.execute(
            "INSERT INTO platform_internal_admins"
            "(user_id, role, active, created_at, updated_at) "
            "VALUES (%s,'platform_admin',1,'2026-01-01T00:00:00Z',"
            "'2026-01-01T00:00:00Z')",
            (operator.id,),
        )
        connection.commit()

    before = _rows(app_dsn, "SELECT count(*) FROM platform_admin_audit")[0][0]
    admin.set_account_state(
        actor_user_id=operator.id,
        public_id=workspace.public_id,
        state="suspended",
        reason_code="security_response",
        reason="Suspended during the launch runtime proof",
    )
    after = _rows(app_dsn, "SELECT count(*) FROM platform_admin_audit")[0][0]
    assert after == before + 1

    recorded = _rows(
        app_dsn,
        "SELECT actor_role, reason_code FROM platform_admin_audit "
        "ORDER BY id DESC LIMIT 1",
    )
    assert recorded == [("platform_admin", "security_response")]


def test_the_admin_audit_table_refuses_update_and_delete(
    platform_backend,
) -> None:
    _, app_dsn, _ = platform_backend
    with psycopg.connect(app_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM platform_admin_audit")
        connection.rollback()
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE platform_admin_audit SET reason='x'")
        connection.rollback()


# --- the durable audit sink --------------------------------------------------


def test_the_access_audit_sink_records_and_reads_back(platform_backend) -> None:
    backend, app_dsn, _ = platform_backend
    audit = PostgresAccessAuditLog(backend)

    first = audit.record(
        workspace_id="ws_alpha", tool="cre_search", decision="allowed", reason=""
    )
    audit.record(
        workspace_id="ws_beta",
        tool="cre_search",
        decision="denied",
        reason="territory",
    )

    alpha = audit.events("ws_alpha")
    assert [event.tool for event in alpha] == ["cre_search"]
    assert alpha[0].decision == "allowed"
    assert alpha[0].ts == first.ts

    assert {event.workspace_id for event in audit.events()} == {
        "ws_alpha",
        "ws_beta",
    }


def test_the_access_audit_sink_is_append_only_in_the_database(
    platform_backend,
) -> None:
    backend, app_dsn, _ = platform_backend
    PostgresAccessAuditLog(backend).record(
        workspace_id="ws_x", tool="cre_search", decision="allowed"
    )
    with psycopg.connect(app_dsn) as connection:
        connection.execute("SET search_path TO medawarcre, pg_catalog")
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE access_audit_log SET decision='denied'")
        connection.rollback()
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM access_audit_log")
        connection.rollback()


# --- the bridge's own compatibility surface ----------------------------------


def test_total_changes_counts_writes_the_way_the_stores_expect(
    platform_backend,
) -> None:
    backend, _, _ = platform_backend
    with backend.connect(transactional=True) as connection:
        before = connection.total_changes
        connection.execute(
            "INSERT INTO platform_users(email,name,created_at,updated_at) "
            "VALUES (?,?,?,?)",
            ("counter@example.com", "Counter", "2026-01-01", "2026-01-01"),
        )
        assert connection.total_changes == before + 1
        connection.execute(
            "SELECT id FROM platform_users WHERE email=?",
            ("counter@example.com",),
        )
        assert connection.total_changes == before + 1


def test_lastrowid_returns_the_generated_identity(platform_backend) -> None:
    backend, _, _ = platform_backend
    with backend.connect(transactional=True) as connection:
        cursor = connection.execute(
            "INSERT INTO platform_users(email,name,created_at,updated_at) "
            "VALUES (?,?,?,?)",
            ("identity@example.com", "Identity", "2026-01-01", "2026-01-01"),
        )
        assert isinstance(cursor.lastrowid, int)
        row = connection.execute(
            "SELECT email FROM platform_users WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
        assert row["email"] == "identity@example.com"
        assert row[0] == "identity@example.com"
        assert dict(row) == {"email": "identity@example.com"}


def test_an_integrity_violation_arrives_as_sqlite3_integrityerror(
    platform_backend,
) -> None:
    backend, _, _ = platform_backend
    with pytest.raises(sqlite3.IntegrityError):
        with backend.connect(transactional=True) as connection:
            for _ in range(2):
                connection.execute(
                    "INSERT INTO platform_users"
                    "(email,name,created_at,updated_at) VALUES (?,?,?,?)",
                    ("clash@example.com", "Clash", "2026-01-01", "2026-01-01"),
                )


def test_a_rolled_back_transaction_leaves_nothing_behind(
    platform_backend,
) -> None:
    backend, app_dsn, _ = platform_backend
    with pytest.raises(sqlite3.IntegrityError):
        with backend.connect(transactional=True) as connection:
            connection.execute(
                "INSERT INTO platform_users(email,name,created_at,updated_at) "
                "VALUES (?,?,?,?)",
                ("ghost@example.com", "Ghost", "2026-01-01", "2026-01-01"),
            )
            connection.execute(
                "INSERT INTO platform_users(email,name,created_at,updated_at) "
                "VALUES (?,?,?,?)",
                ("ghost@example.com", "Ghost", "2026-01-01", "2026-01-01"),
            )
    assert _rows(
        app_dsn,
        "SELECT count(*) FROM platform_users WHERE email=%s",
        ("ghost@example.com",),
    ) == [(0,)]


# --- the internal Operations Console's data layer ----------------------------


def test_the_operations_console_reads_the_real_postgresql_backend(
    platform_backend,
) -> None:
    """The founder decision that the Console must not sit on SQLite, tested.

    `OperationsReadStore` is what `web/operations` reads through. It opened a
    SQLite file directly until the authority port; it now resolves the same
    backend every other platform store does, so this asserts that its answers
    come from rows written to PostgreSQL rather than from a local prototype
    database that happens to exist.
    """
    from cre_mcp.platform.operations import OperationsReadStore

    _, app_dsn, unused = platform_backend
    repository = PlatformRepository(config=_config(unused))
    store = OperationsReadStore(unused)

    baseline = store.health()
    assert baseline["status"] == "ready"
    assert baseline["database"] == "reachable"

    async def scenario():
        workspace = await repository.create_workspace("Console Visible Tenant")
        user = await repository.create_user("console@example.test", "Console")
        await repository.add_membership(workspace.public_id, user.id, "owner")
        return workspace

    workspace = asyncio.run(scenario())

    after = store.health()
    assert after["workspaces"] == baseline["workspaces"] + 1

    found = store.search_workspaces("Console Visible")
    names = {item["name"] for item in found["workspaces"]}
    assert "Console Visible Tenant" in names

    # And the row the Console just reported is genuinely in PostgreSQL, not in
    # a file the store might have fallen back to.
    assert _rows(
        app_dsn,
        "SELECT name FROM platform_workspaces WHERE public_id=%s",
        (workspace.public_id,),
    ) == [("Console Visible Tenant",)]
    assert not unused.exists()
