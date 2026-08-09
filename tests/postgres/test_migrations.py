from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.postgres.migrations import (
    ChecksumMismatchError,
    DirtyMigrationError,
    Migration,
    MigrationGapError,
    MigrationRunner,
    UnsafeMigrationRoleError,
    load_migrations,
)


def test_real_migrations_are_idempotent_and_checksums_are_enforced(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    migrations = load_migrations()
    runner = MigrationRunner(migration_dsn, migrations)
    assert runner.apply() == [migration.version for migration in migrations]
    assert runner.apply() == []

    changed = Migration.from_sql(
        migrations[0].version,
        migrations[0].name,
        migrations[0].sql + "\nSELECT 1;",
    )
    with pytest.raises(ChecksumMismatchError):
        MigrationRunner(migration_dsn, [changed]).apply()

    with psycopg.connect(admin_dsn) as connection:
        rows = connection.execute(
            "SELECT version,state,dirty FROM medawarcre.schema_migrations "
            "ORDER BY version"
        ).fetchall()
    assert rows == [(migration.version, "applied", False) for migration in migrations]


def test_failed_migration_is_dirty_until_checksum_bound_recovery(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    base = load_migrations()
    MigrationRunner(migration_dsn, base).apply()
    failing = Migration.from_sql(
        len(base) + 1,
        "requires explicit operator repair",
        """
        CREATE TABLE medawarcre.recovery_proof (
            id bigint PRIMARY KEY REFERENCES medawarcre.operator_prerequisite(id)
        );
        """,
    )
    runner = MigrationRunner(migration_dsn, [*base, failing])

    with pytest.raises(psycopg.Error):
        runner.apply()
    with pytest.raises(DirtyMigrationError):
        runner.apply()

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "CREATE TABLE medawarcre.operator_prerequisite (id bigint PRIMARY KEY)"
        )

    with pytest.raises(ChecksumMismatchError):
        runner.recover_failed(
            failing.version,
            checksum="0" * 64,
            reason="test repair",
        )
    runner.recover_failed(
        failing.version,
        checksum=failing.checksum,
        reason="created the missing prerequisite table",
    )
    assert runner.apply() == [failing.version]


def test_migration_gap_fails_before_database_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    _, migration_dsn, _ = postgres_database
    gap = Migration.from_sql(2, "gap", "SELECT 1;")
    with pytest.raises(MigrationGapError):
        MigrationRunner(migration_dsn, [gap]).apply()


def test_concurrent_runners_serialize_with_one_ledger_write(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    migrations = load_migrations()

    def apply() -> list[int]:
        return MigrationRunner(migration_dsn, migrations).apply()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: apply(), range(2)))
    assert sorted(outcomes, key=len) == [[], [m.version for m in migrations]]

    with psycopg.connect(admin_dsn) as connection:
        count = connection.execute(
            "SELECT count(*) FROM medawarcre.schema_migrations"
        ).fetchone()[0]
    assert count == len(migrations)


def test_deal_upgrade_converts_actor_owned_rows_to_collaborative_attribution(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, migration_dsn, _ = postgres_database
    migrations = load_migrations()
    # Sliced by version rather than by position. These tests exercise the
    # 0008 deal upgrade, and `migrations[:-1]` meant "everything before 0008"
    # only while 0008 happened to be last; adding 0009 silently turned it into
    # "everything including 0008", so the legacy row could no longer be
    # inserted. Naming the version keeps the test about what it is about.
    before_0008 = [item for item in migrations if item.version < 8]
    from_0008 = [item.version for item in migrations if item.version >= 8]
    MigrationRunner(migration_dsn, before_0008).apply()
    actor_id = str(uuid4())
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Legacy Owner','active')",
            (actor_id, f"legacy-{uuid4().hex}@example.test"),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Legacy Deal Workspace','active')",
            (workspace_id, f"ws_{uuid4().hex}"),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(id,workspace_id,user_id,role,state) "
            "VALUES (%s,%s,%s,'owner','active')",
            (str(uuid4()), workspace_id, actor_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "workspace_id,source,source_record_id,title,listing,owner_user_id) "
            "VALUES (%s,'crexi','legacy-1','Legacy Deal',"
            "'{\"source\":\"crexi\",\"source_id\":\"legacy-1\","
            "\"name\":\"Legacy Deal\"}'::jsonb,%s)",
            (workspace_id, actor_id),
        )

    assert MigrationRunner(migration_dsn, migrations).apply() == from_0008
    with psycopg.connect(admin_dsn) as connection:
        row = connection.execute(
            "SELECT owner_user_id,created_by_user_id::text,updated_by_user_id::text "
            "FROM medawarcre.deals WHERE workspace_id=%s",
            (workspace_id,),
        ).fetchone()
    assert row == (None, actor_id, actor_id)


def test_migration_apply_and_recovery_reject_superuser_before_mutation(
    postgres_database: tuple[str, str, str],
) -> None:
    admin_dsn, _, _ = postgres_database
    migration = load_migrations()[0]
    runner = MigrationRunner(admin_dsn, [migration])

    with pytest.raises(UnsafeMigrationRoleError):
        runner.apply()
    with pytest.raises(UnsafeMigrationRoleError):
        runner.recover_failed(
            migration.version,
            checksum=migration.checksum,
            reason="operator recovery proof",
        )

    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT to_regclass('medawarcre.schema_migrations')"
        ).fetchone() == (None,)
