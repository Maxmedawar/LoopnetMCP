from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
