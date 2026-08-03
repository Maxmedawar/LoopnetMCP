"""Small, transactional schema migrations for platform subcomponents."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime


MigrationStep = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: MigrationStep


def _ensure_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_schema_versions (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY(component, version)
        )
        """
    )


def current_version(connection: sqlite3.Connection, component: str) -> int:
    """Return the highest applied version for one independently-owned schema."""
    _ensure_version_table(connection)
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM platform_schema_versions "
        "WHERE component=?",
        (component,),
    ).fetchone()
    return int(row[0])


def apply_migrations(
    connection: sqlite3.Connection,
    component: str,
    migrations: Sequence[Migration],
) -> int:
    """Apply pending migrations one at a time with atomic version recording.

    Migration callbacks must use ``execute`` rather than ``executescript``:
    Python's SQLite ``executescript`` commits implicitly and would defeat the
    rollback guarantee this runner provides.
    """
    component = component.strip()
    if not component:
        raise ValueError("migration component is required")

    _ensure_version_table(connection)
    applied = current_version(connection, component)
    for migration in sorted(migrations, key=lambda item: item.version):
        if migration.version <= applied:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            locked_applied = current_version(connection, component)
            if migration.version <= locked_applied:
                connection.commit()
                applied = locked_applied
                continue
            if migration.version != locked_applied + 1:
                raise ValueError(
                    f"migration gap for {component}: expected {locked_applied + 1}, "
                    f"got {migration.version}"
                )
            migration.apply(connection)
            connection.execute(
                "INSERT INTO platform_schema_versions"
                "(component,version,description,applied_at) VALUES (?,?,?,?)",
                (
                    component,
                    migration.version,
                    migration.description,
                    datetime.now(UTC).isoformat(),
                ),
            )
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
            applied = migration.version
    return applied


__all__ = ["Migration", "apply_migrations", "current_version"]
