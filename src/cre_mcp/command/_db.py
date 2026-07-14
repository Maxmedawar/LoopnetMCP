"""Shared, read-only access helpers for command-center projections."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore


def resolve_db_path(
    db_path: str | Path | CreConfig | None = None,
) -> Path:
    """Resolve the shared cache path through the existing DealStore contract."""
    return DealStore(db_path).db_path


@contextmanager
def read_connection(
    db_path: str | Path | CreConfig | None = None,
) -> Iterator[sqlite3.Connection]:
    """Open the shared database in SQLite's read-only/query-only mode."""
    path = resolve_db_path(db_path)
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    try:
        yield connection
    finally:
        connection.close()


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    """Return whether a named table exists without mutating the database."""
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None

