"""Persistent SQLite-backed cache."""

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteCache:
    """Async persistent cache using one short-lived SQLite connection per operation."""

    def __init__(self, db_path: str | Path, ttl_seconds: int = 30 * 24 * 60 * 60):
        self.db_path = Path(db_path).expanduser()
        self.ttl_seconds = ttl_seconds

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl REAL NOT NULL
            )
            """
        )
        return connection

    def _get(self, key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value, created_at, ttl FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            value, created_at, ttl = row
            if time.time() - float(created_at) >= float(ttl):
                connection.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            return json.loads(value)

    async def get(self, key: str) -> Any | None:
        """Return a cached value, deleting it first when its TTL has elapsed."""
        return await asyncio.to_thread(self._get, key)

    def _set(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        payload = json.dumps(value, separators=(",", ":"), default=str)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cache(key, value, created_at, ttl)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    created_at = excluded.created_at,
                    ttl = excluded.ttl
                """,
                (key, payload, time.time(), float(ttl)),
            )

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Insert or replace a cached value."""
        await asyncio.to_thread(self._set, key, value, ttl_seconds)

    def _clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cache")

    async def clear(self) -> None:
        """Remove every cached value without touching other database tables."""
        await asyncio.to_thread(self._clear)

    def _evict_expired(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM cache WHERE created_at + ttl <= ?",
                (time.time(),),
            )
            return cursor.rowcount

    async def evict_expired(self) -> int:
        """Delete all expired rows and return the number removed."""
        return await asyncio.to_thread(self._evict_expired)

