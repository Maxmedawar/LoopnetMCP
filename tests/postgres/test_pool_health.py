from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.health import check_liveness, check_readiness
from cre_mcp.postgres.migrations import MigrationRunner, load_migrations
from cre_mcp.postgres.pool import (
    AuthorityContext,
    PostgresDatabase,
    UnsafeRuntimeRoleError,
)


def test_pool_context_is_transaction_local_and_readiness_is_strict(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    workspace_id, user_id = str(uuid4()), str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name) VALUES (%s,'pool@example.test','Pool')",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name) VALUES (%s,'ws_pool','Pool')",
            (workspace_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(workspace_id,user_id,role,state) "
            "VALUES (%s,%s,'owner','active')",
            (workspace_id, user_id),
        )

    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1, acquire_timeout=3)
    )
    database.open(wait=True)
    try:
        context = AuthorityContext.tenant(workspace_id, user_id)
        with database.connection(context) as connection:
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.workspaces"
            ).fetchone()[0] == 1
        with pytest.raises(ValueError, match="app pool requires tenant authority"):
            with database.connection() as connection:
                connection.execute("SELECT * FROM medawarcre.oauth_clients")
        assert check_liveness(database).ok is True
        readiness = check_readiness(database, expected=load_migrations())
        assert readiness.ok is True
        assert readiness.dirty_versions == ()

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("CREATE TABLE medawarcre.unexpected(id integer)")
        readiness = check_readiness(database, expected=load_migrations())
        assert readiness.ok is False
        assert readiness.unexpected_tables == ("unexpected",)
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("DROP TABLE medawarcre.unexpected")
            connection.execute(
                "INSERT INTO medawarcre.schema_migrations"
                "(version,description,checksum,state,dirty) "
                "VALUES (2,'unexpected',%s,'pending',false)",
                ("0" * 64,),
            )
        readiness = check_readiness(database, expected=load_migrations())
        assert readiness.ok is False
        assert readiness.unexpected_versions == (2,)
        assert readiness.non_applied_versions == (2,)
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "DELETE FROM medawarcre.schema_migrations WHERE version=2"
            )
            connection.execute(
                "UPDATE medawarcre.schema_migrations "
                "SET description='renamed',checksum=%s,state='pending' "
                "WHERE version=1",
                ("f" * 64,),
            )
        readiness = check_readiness(database, expected=load_migrations())
        assert readiness.ok is False
        assert readiness.non_applied_versions == (1,)
        assert readiness.checksum_mismatches == (1,)
        assert readiness.description_mismatches == (1,)
    finally:
        database.close()


def test_pool_discards_stale_connection_after_server_restart(
    postgres_cluster,
) -> None:
    _, migration_dsn, app_dsn = postgres_cluster.create_database("stale")
    MigrationRunner(migration_dsn, load_migrations()).apply()
    database = PostgresDatabase(
        PostgresSettings(
            dsn=app_dsn,
            min_size=1,
            max_size=1,
            acquire_timeout=8,
            reconnect_timeout=8,
        )
    )
    database.open(wait=True)
    try:
        assert check_liveness(database).ok is True
        postgres_cluster.stop("immediate")
        postgres_cluster.start()
        assert check_liveness(database).ok is True
    finally:
        database.close()


def test_admin_pool_rejects_contextless_arbitrary_sql(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    admin_login_dsn = app_dsn.replace(
        "user=medawarcre_test_app", "user=medawarcre_test_admin"
    )
    database = PostgresDatabase(
        PostgresSettings(
            dsn=admin_login_dsn,
            min_size=1,
            max_size=1,
            runtime_mode="admin",
        )
    )
    database.open(wait=True)
    try:
        with pytest.raises(ValueError, match="admin pool requires internal authority"):
            with database.connection() as connection:
                connection.execute("SELECT * FROM medawarcre.oauth_clients")
        assert check_liveness(database).ok is True
        assert check_readiness(database, expected=load_migrations()).ok is True
    finally:
        database.close()


def test_runtime_pool_rejects_superuser_and_migration_dsn(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    for unsafe_dsn in (admin_dsn, migration_dsn):
        database = PostgresDatabase(
            PostgresSettings(dsn=unsafe_dsn, min_size=0, max_size=1)
        )
        with pytest.raises(UnsafeRuntimeRoleError):
            database.open(wait=True)
        database.close()


@pytest.mark.parametrize("capability", ["CREATEDB", "CREATEROLE", "REPLICATION"])
def test_runtime_pool_rejects_cluster_capabilities(
    postgres_database: tuple[str, str, str], capability: str
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    role_name = f"medawarcre_test_unsafe_{capability.casefold()}_{uuid4().hex[:8]}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN {}").format(
                sql.Identifier(role_name), sql.SQL(capability)
            )
        )
        connection.execute(
            sql.SQL("GRANT medawarcre_app TO {}").format(sql.Identifier(role_name))
        )
    unsafe_dsn = admin_dsn.replace("user=postgres", f"user={role_name}")
    database = PostgresDatabase(
        PostgresSettings(dsn=unsafe_dsn, min_size=0, max_size=1)
    )
    with pytest.raises(UnsafeRuntimeRoleError):
        database.open(wait=True)
    database.close()


def test_runtime_pool_rejects_transitive_bypassrls_membership(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    MigrationRunner(migration_dsn, load_migrations()).apply()
    suffix = uuid4().hex[:8]
    login_role = f"medawarcre_test_safe_login_{suffix}"
    bypass_role = f"medawarcre_test_bypass_group_{suffix}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN BYPASSRLS").format(
                sql.Identifier(bypass_role)
            )
        )
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(login_role))
        )
        connection.execute(
            sql.SQL("GRANT medawarcre_app, {} TO {}").format(
                sql.Identifier(bypass_role), sql.Identifier(login_role)
            )
        )
    unsafe_dsn = admin_dsn.replace("user=postgres", f"user={login_role}")
    database = PostgresDatabase(
        PostgresSettings(dsn=unsafe_dsn, min_size=0, max_size=1)
    )
    with pytest.raises(UnsafeRuntimeRoleError):
        database.open(wait=True)
    database.close()


def test_readiness_rejects_exact_rls_and_catalog_drift(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    migrations = load_migrations()
    MigrationRunner(migration_dsn, migrations).apply()
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=1)
    )
    database.open(wait=True)
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("ALTER TABLE medawarcre.users DISABLE ROW LEVEL SECURITY")
        readiness = check_readiness(database, expected=migrations)
        assert readiness.ok is False
        assert readiness.missing_rls == ("users",)
        assert readiness.schema_drift is True

        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("ALTER TABLE medawarcre.users ENABLE ROW LEVEL SECURITY")
        assert check_readiness(database, expected=migrations).ok is True

        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("ALTER TABLE medawarcre.plans ENABLE ROW LEVEL SECURITY")
        readiness = check_readiness(database, expected=migrations)
        assert readiness.ok is False
        assert readiness.unexpected_rls == ("plans",)
        assert readiness.schema_drift is True

        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute("ALTER TABLE medawarcre.plans DISABLE ROW LEVEL SECURITY")
            connection.execute("DROP INDEX medawarcre.deals_workspace_stage_idx")
        readiness = check_readiness(database, expected=migrations)
        assert readiness.ok is False
        assert readiness.missing_rls == ()
        assert readiness.unexpected_rls == ()
        assert readiness.schema_drift is True
    finally:
        database.close()
