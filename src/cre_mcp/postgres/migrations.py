"""Serialized, checksummed PostgreSQL migrations with explicit dirty recovery."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Sequence

import psycopg
from psycopg import sql

from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_exact_group_session,
)
from cre_mcp.postgres.schema import SCHEMA_NAME

MIGRATION_ROLE = "medawarcre_migration"
MIGRATION_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"medawarcre-schema-migrations-v1").digest()[:8],
    byteorder="big",
    signed=True,
)
_MIGRATION_FILE = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Base class for safe migration-control failures."""


class MigrationGapError(MigrationError):
    pass


class DirtyMigrationError(MigrationError):
    pass


class ChecksumMismatchError(MigrationError):
    pass


class UnknownMigrationError(MigrationError):
    pass


class UnsafeMigrationRoleError(MigrationError):
    """The migration DSN can exceed the dedicated migration authority."""


def assert_migration_session(connection: psycopg.Connection) -> None:
    """Require one safe login with exactly the migration group membership."""
    try:
        assert_exact_group_session(
            connection,
            MIGRATION_ROLE,
            allow_database_owner_membership=True,
            allow_effective_ownership=True,
        )
    except UnsafeDatabaseRoleError as error:
        raise UnsafeMigrationRoleError(
            "migration login violates the dedicated authority contract"
        ) from error


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str

    @classmethod
    def from_sql(cls, version: int, name: str, statement: str) -> "Migration":
        if version <= 0:
            raise ValueError("migration version must be positive")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("migration name is required")
        if not statement.strip():
            raise ValueError("migration SQL is required")
        checksum = hashlib.sha256(statement.encode("utf-8")).hexdigest()
        return cls(version, normalized_name, statement, checksum)


def load_migrations() -> tuple[Migration, ...]:
    """Load immutable SQL resources in numeric order."""
    root = files("cre_mcp.postgres").joinpath("sql")
    migrations: list[Migration] = []
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        match = _MIGRATION_FILE.fullmatch(resource.name)
        if match is None:
            continue
        statement = resource.read_text(encoding="utf-8")
        name = match.group("name").replace("_", " ")
        migrations.append(
            Migration.from_sql(int(match.group("version")), name, statement)
        )
    _validate_sequence(migrations)
    return tuple(migrations)


def _validate_sequence(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if len(set(versions)) != len(versions):
        raise MigrationGapError("duplicate migration version")
    expected = list(range(1, len(versions) + 1))
    if versions != expected:
        raise MigrationGapError(
            f"migration versions must be contiguous from 1: expected {expected}, got {versions}"
        )


def _failure_code(error: BaseException) -> str:
    if isinstance(error, psycopg.Error) and error.sqlstate:
        return error.sqlstate
    return type(error).__name__[:80]


class MigrationRunner:
    """Apply one immutable migration plan under a database-local advisory lock."""

    def __init__(
        self,
        dsn: str,
        migrations: Sequence[Migration] | None = None,
        *,
        role: str = MIGRATION_ROLE,
    ) -> None:
        if not dsn.strip():
            raise ValueError("database DSN is required")
        selected = tuple(load_migrations() if migrations is None else migrations)
        _validate_sequence(selected)
        if role != MIGRATION_ROLE:
            raise ValueError("unsupported migration role")
        self._dsn = dsn
        self.migrations = selected
        self.role = role

    @staticmethod
    def _set_role(connection: psycopg.Connection, role: str) -> None:
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))

    @staticmethod
    def _ensure_ledger(connection: psycopg.Connection) -> None:
        connection.execute(
            "CREATE SCHEMA IF NOT EXISTS medawarcre AUTHORIZATION medawarcre_migration"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS medawarcre.schema_migrations (
                version integer PRIMARY KEY CHECK (version > 0),
                description text NOT NULL,
                checksum character(64) NOT NULL,
                state text NOT NULL CHECK (state IN ('pending','running','failed','applied')),
                dirty boolean NOT NULL,
                attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                started_at timestamptz,
                applied_at timestamptz,
                failed_at timestamptz,
                failure_code text,
                recovery_count integer NOT NULL DEFAULT 0 CHECK (recovery_count >= 0),
                recovered_at timestamptz,
                recovery_reason text,
                CHECK ((state = 'applied' AND NOT dirty AND applied_at IS NOT NULL)
                    OR state <> 'applied')
            )
            """
        )
        connection.execute(
            "REVOKE ALL ON medawarcre.schema_migrations FROM PUBLIC"
        )
        connection.execute(
            "GRANT SELECT ON medawarcre.schema_migrations "
            "TO medawarcre_app, medawarcre_admin, medawarcre_backup"
        )

    def _lock(self, connection: psycopg.Connection) -> None:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))

    def _unlock(self, connection: psycopg.Connection) -> None:
        connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))

    def _history(self, connection: psycopg.Connection) -> list[tuple]:
        return connection.execute(
            "SELECT version,description,checksum,state,dirty "
            "FROM medawarcre.schema_migrations ORDER BY version"
        ).fetchall()

    def _validate_history(self, history: Iterable[tuple]) -> set[int]:
        by_version = {migration.version: migration for migration in self.migrations}
        applied: set[int] = set()
        dirty: list[int] = []
        for version, description, checksum, state, is_dirty in history:
            migration = by_version.get(int(version))
            if migration is None:
                raise UnknownMigrationError(
                    f"database contains unknown migration version {version}"
                )
            if str(checksum) != migration.checksum:
                raise ChecksumMismatchError(
                    f"migration {version} checksum differs from the immutable plan"
                )
            if str(description) != migration.name:
                raise ChecksumMismatchError(
                    f"migration {version} description differs from the immutable plan"
                )
            if bool(is_dirty):
                dirty.append(int(version))
            if state == "applied":
                applied.add(int(version))
        if dirty:
            raise DirtyMigrationError(
                "dirty migration blocks execution: " + ", ".join(map(str, dirty))
            )
        if applied and applied != set(range(1, max(applied) + 1)):
            raise MigrationGapError("applied migration history contains a gap")
        return applied

    def apply(self) -> list[int]:
        applied_now: list[int] = []
        with psycopg.connect(self._dsn, autocommit=True) as connection:
            assert_migration_session(connection)
            self._set_role(connection, self.role)
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                already_applied = self._validate_history(self._history(connection))
                for migration in self.migrations:
                    if migration.version in already_applied:
                        continue
                    row = connection.execute(
                        "SELECT state,dirty,checksum FROM medawarcre.schema_migrations "
                        "WHERE version=%s",
                        (migration.version,),
                    ).fetchone()
                    if row is None:
                        connection.execute(
                            "INSERT INTO medawarcre.schema_migrations"
                            "(version,description,checksum,state,dirty,attempt_count,started_at) "
                            "VALUES (%s,%s,%s,'running',true,1,statement_timestamp())",
                            (migration.version, migration.name, migration.checksum),
                        )
                    else:
                        state, is_dirty, checksum = row
                        if str(checksum) != migration.checksum:
                            raise ChecksumMismatchError(
                                f"migration {migration.version} checksum differs from recovery row"
                            )
                        if is_dirty or state != "pending":
                            raise DirtyMigrationError(
                                f"migration {migration.version} requires explicit recovery"
                            )
                        connection.execute(
                            "UPDATE medawarcre.schema_migrations "
                            "SET state='running',dirty=true,attempt_count=attempt_count+1,"
                            "started_at=statement_timestamp(),failed_at=NULL,failure_code=NULL "
                            "WHERE version=%s",
                            (migration.version,),
                        )
                    try:
                        with connection.transaction():
                            connection.execute(migration.sql)
                            connection.execute(
                                "UPDATE medawarcre.schema_migrations "
                                "SET state='applied',dirty=false,"
                                "applied_at=statement_timestamp(),failed_at=NULL,failure_code=NULL "
                                "WHERE version=%s",
                                (migration.version,),
                            )
                    except BaseException as error:
                        connection.execute(
                            "UPDATE medawarcre.schema_migrations "
                            "SET state='failed',dirty=true,failed_at=statement_timestamp(),"
                            "failure_code=%s WHERE version=%s",
                            (_failure_code(error), migration.version),
                        )
                        raise
                    applied_now.append(migration.version)
            finally:
                self._unlock(connection)
        return applied_now

    def recover_failed(self, version: int, *, checksum: str, reason: str) -> None:
        normalized_reason = reason.strip()
        if len(normalized_reason) < 8:
            raise ValueError("recovery reason must contain at least 8 characters")
        with psycopg.connect(self._dsn, autocommit=True) as connection:
            assert_migration_session(connection)
            self._set_role(connection, self.role)
            self._lock(connection)
            try:
                self._ensure_ledger(connection)
                row = connection.execute(
                    "SELECT checksum,state,dirty FROM medawarcre.schema_migrations "
                    "WHERE version=%s",
                    (version,),
                ).fetchone()
                if row is None:
                    raise DirtyMigrationError(f"migration {version} has no failure row")
                stored_checksum, state, is_dirty = row
                if str(stored_checksum) != checksum:
                    raise ChecksumMismatchError(
                        f"migration {version} recovery checksum does not match"
                    )
                if not is_dirty or state not in {"failed", "running"}:
                    raise DirtyMigrationError(
                        f"migration {version} is not in a recoverable dirty state"
                    )
                connection.execute(
                    "UPDATE medawarcre.schema_migrations "
                    "SET state='pending',dirty=false,recovery_count=recovery_count+1,"
                    "recovered_at=statement_timestamp(),recovery_reason=%s "
                    "WHERE version=%s",
                    (normalized_reason, version),
                )
            finally:
                self._unlock(connection)


__all__ = [
    "ChecksumMismatchError",
    "DirtyMigrationError",
    "MIGRATION_LOCK_ID",
    "Migration",
    "MigrationError",
    "MigrationGapError",
    "MigrationRunner",
    "UnknownMigrationError",
    "UnsafeMigrationRoleError",
    "assert_migration_session",
    "load_migrations",
]
