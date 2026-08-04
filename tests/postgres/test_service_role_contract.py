from __future__ import annotations

import psycopg
import pytest

from cre_mcp.postgres.authority import (
    SERVICE_ROLES,
    UnsafeDatabaseRoleError,
    assert_service_session,
)
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.pool import AuthorityContext, PostgresDatabase


EXPECTED_SERVICE_ROLES = {
    "oauth": "medawarcre_oauth",
    "provider_ingress": "medawarcre_provider_ingress",
    "provider_reconcile": "medawarcre_provider_reconcile",
    "worker": "medawarcre_worker",
    "scheduler": "medawarcre_scheduler",
}


def test_service_role_vocabulary_is_exact() -> None:
    assert SERVICE_ROLES == EXPECTED_SERVICE_ROLES


def test_bootstrap_creates_non_inheriting_no_login_service_roles(
    postgres_cluster,
) -> None:
    with psycopg.connect(postgres_cluster.dsn()) as connection:
        rows = connection.execute(
            "SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolbypassrls,"
            "rolcreatedb,rolcreaterole,rolreplication "
            "FROM pg_catalog.pg_roles WHERE rolname=ANY(%s) ORDER BY rolname",
            (list(EXPECTED_SERVICE_ROLES.values()),),
        ).fetchall()
    assert rows == [
        (role, False, False, False, False, False, False, False)
        for role in sorted(EXPECTED_SERVICE_ROLES.values())
    ]


@pytest.mark.parametrize("mode,group_role", EXPECTED_SERVICE_ROLES.items())
def test_service_login_preflight_requires_its_one_exact_role(
    postgres_database: tuple[str, str, str],
    mode: str,
    group_role: str,
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    service_dsn = admin_dsn.replace("user=postgres", f"user=medawarcre_test_{mode}")
    with psycopg.connect(service_dsn) as connection:
        assert_service_session(connection, mode)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM medawarcre.workspaces")
        connection.rollback()
        connection.execute(f"SET ROLE {group_role}")
        assert connection.execute("SELECT current_user").fetchone() == (group_role,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT count(*) FROM medawarcre.workspaces")


def test_service_login_preflight_rejects_a_different_service_identity(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    oauth_dsn = admin_dsn.replace("user=postgres", "user=medawarcre_test_oauth")
    with psycopg.connect(oauth_dsn) as connection:
        connection.execute("SET search_path TO public, pg_catalog")
        assert connection.execute("SHOW search_path").fetchone() == (
            "public, pg_catalog",
        )
        assert_service_session(connection, "oauth")
        assert connection.execute("SHOW search_path").fetchone() == (
            "pg_catalog",
        )
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_service_session(connection, "worker")


def test_service_login_preflight_rejects_group_role_acl_drift(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    oauth_dsn = admin_dsn.replace("user=postgres", "user=medawarcre_test_oauth")
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "GRANT SELECT ON medawarcre.workspaces TO medawarcre_oauth"
        )
    with psycopg.connect(oauth_dsn) as connection:
        with pytest.raises(UnsafeDatabaseRoleError):
            assert_service_session(connection, "oauth")


def test_runtime_pool_pins_catalog_search_path(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    database.open(wait=True)
    try:
        context = AuthorityContext.tenant(
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        )
        with database.connection(context) as connection:
            assert connection.execute("SHOW search_path").fetchone() == (
                "pg_catalog",
            )
            connection.execute("SET search_path TO public, pg_catalog")
        with database.connection(context) as connection:
            assert connection.execute("SHOW search_path").fetchone() == (
                "pg_catalog",
            )
    finally:
        database.close()
