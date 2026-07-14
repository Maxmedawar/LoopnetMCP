"""Persistent deal and diligence state on the existing SQLite database."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from cre_mcp.config import CreConfig
from cre_mcp.models.execution import DDItem
from cre_mcp.models.listings import Listing

logger = logging.getLogger(__name__)

DD_STATUSES = frozenset({"not_started", "in_progress", "blocked", "complete", "waived"})


class DealStore:
    """Async façade over durable deal/checklist tables in the shared cache DB."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if isinstance(db_path, CreConfig):
            resolved = db_path.cache_db_path
        else:
            resolved = db_path or (config or CreConfig()).cache_db_path
        self.db_path = Path(resolved).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                listing_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_deals_source_id
                ON deals(source, source_id);

            CREATE TABLE IF NOT EXISTS dd_items (
                deal_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_json TEXT NOT NULL,
                status TEXT NOT NULL,
                deadline TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(deal_id, item_key),
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_dd_items_deadline
                ON dd_items(deal_id, deadline);
            """
        )
        return connection

    @staticmethod
    def deal_id_for(listing: Listing) -> str:
        """Return the stable source-qualified identifier used across later phases."""
        source = listing.source.strip()
        source_id = listing.source_id.strip()
        if not source or not source_id:
            raise ValueError("listing source and source_id are required to save a deal")
        return f"{source}:{source_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _save_deal(self, listing: Listing) -> str:
        deal_id = self.deal_id_for(listing)
        now = self._now()
        payload = listing.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deals(
                    deal_id, source, source_id, listing_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET
                    listing_json = excluded.listing_json,
                    updated_at = excluded.updated_at
                """,
                (deal_id, listing.source, listing.source_id, payload, now, now),
            )
        return deal_id

    async def save_deal(self, listing: Listing) -> str | None:
        """Save or refresh a listing; persistence failure is logged, not raised."""
        try:
            return await asyncio.to_thread(self._save_deal, listing)
        except Exception as exc:
            logger.error("deal store save failed for %s:%s: %s", listing.source, listing.source_id, exc)
            return None

    @staticmethod
    def _decode_item(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["item_json"]))
        payload["status"] = row["status"]
        payload["deadline"] = row["deadline"]
        return payload

    def _get_deal(self, deal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT deal_id, source, source_id, listing_json, created_at, updated_at
                FROM deals WHERE deal_id = ?
                """,
                (deal_id,),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                """
                SELECT item_json, status, deadline
                FROM dd_items WHERE deal_id = ?
                ORDER BY deadline, item_key
                """,
                (deal_id,),
            ).fetchall()
        return {
            "deal_id": row["deal_id"],
            "source": row["source"],
            "source_id": row["source_id"],
            "listing": json.loads(str(row["listing_json"])),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "dd_items": [self._decode_item(item) for item in items],
        }

    async def get_deal(self, deal_id: str) -> dict[str, Any] | None:
        """Return a stored deal plus its current diligence items."""
        try:
            return await asyncio.to_thread(self._get_deal, deal_id)
        except Exception as exc:
            logger.error("deal store read failed for %s: %s", deal_id, exc)
            return None

    def _save_dd_items(self, deal_id: str, items: Iterable[DDItem]) -> bool:
        now = self._now()
        materialized = list(items)
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if exists is None:
                return False
            for item in materialized:
                previous = connection.execute(
                    "SELECT status FROM dd_items WHERE deal_id = ? AND item_key = ?",
                    (deal_id, item.key),
                ).fetchone()
                status = str(previous["status"]) if previous is not None else item.status
                persisted = item.model_copy(update={"status": status})
                connection.execute(
                    """
                    INSERT INTO dd_items(
                        deal_id, item_key, item_json, status, deadline, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deal_id, item_key) DO UPDATE SET
                        item_json = excluded.item_json,
                        status = excluded.status,
                        deadline = excluded.deadline,
                        updated_at = excluded.updated_at
                    """,
                    (
                        deal_id,
                        item.key,
                        persisted.model_dump_json(),
                        status,
                        item.deadline.isoformat(),
                        now,
                    ),
                )
            active_keys = [item.key for item in materialized]
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                connection.execute(
                    f"DELETE FROM dd_items WHERE deal_id = ? AND item_key NOT IN ({placeholders})",
                    (deal_id, *active_keys),
                )
            else:
                connection.execute("DELETE FROM dd_items WHERE deal_id = ?", (deal_id,))
        return True

    async def save_dd_items(self, deal_id: str, items: Iterable[DDItem]) -> bool:
        """Upsert a generated plan while retaining already-recorded statuses."""
        materialized = list(items)
        try:
            return await asyncio.to_thread(self._save_dd_items, deal_id, materialized)
        except Exception as exc:
            logger.error("diligence persistence failed for %s: %s", deal_id, exc)
            return False

    def _get_dd_items(self, deal_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_json, status, deadline
                FROM dd_items WHERE deal_id = ?
                ORDER BY deadline, item_key
                """,
                (deal_id,),
            ).fetchall()
        return [self._decode_item(row) for row in rows]

    async def get_dd_items(self, deal_id: str) -> list[dict[str, Any]]:
        """Return current checklist rows in deadline order."""
        try:
            return await asyncio.to_thread(self._get_dd_items, deal_id)
        except Exception as exc:
            logger.error("diligence read failed for %s: %s", deal_id, exc)
            return []

    def _set_dd_item_status(self, deal_id: str, key: str, status: str) -> bool:
        if status not in DD_STATUSES:
            raise ValueError(
                f"status must be one of {', '.join(sorted(DD_STATUSES))}"
            )
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT item_json FROM dd_items
                WHERE deal_id = ? AND item_key = ?
                """,
                (deal_id, key),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(str(row["item_json"]))
            payload["status"] = status
            cursor = connection.execute(
                """
                UPDATE dd_items
                SET status = ?, item_json = ?, updated_at = ?
                WHERE deal_id = ? AND item_key = ?
                """,
                (
                    status,
                    json.dumps(payload, separators=(",", ":")),
                    now,
                    deal_id,
                    key,
                ),
            )
        return cursor.rowcount == 1

    async def set_dd_item_status(self, deal_id: str, key: str, status: str) -> bool:
        """Update one known item; invalid states are rejected, DB failures are non-fatal."""
        if status not in DD_STATUSES:
            raise ValueError(
                f"status must be one of {', '.join(sorted(DD_STATUSES))}"
            )
        try:
            return await asyncio.to_thread(self._set_dd_item_status, deal_id, key, status)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("diligence status update failed for %s/%s: %s", deal_id, key, exc)
            return False

    def _list_deals(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    d.deal_id, d.source, d.source_id, d.listing_json,
                    d.created_at, d.updated_at,
                    COUNT(i.item_key) AS dd_total,
                    SUM(CASE WHEN i.status = 'complete' THEN 1 ELSE 0 END) AS dd_complete
                FROM deals d
                LEFT JOIN dd_items i ON i.deal_id = d.deal_id
                GROUP BY d.deal_id
                ORDER BY d.updated_at DESC, d.deal_id
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            listing = json.loads(str(row["listing_json"]))
            results.append(
                {
                    "deal_id": row["deal_id"],
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "name": listing.get("name"),
                    "address": listing.get("address"),
                    "city": listing.get("city"),
                    "state": listing.get("state"),
                    "price_usd": listing.get("price_usd"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "dd_total": int(row["dd_total"] or 0),
                    "dd_complete": int(row["dd_complete"] or 0),
                }
            )
        return results

    async def list_deals(self) -> list[dict[str, Any]]:
        """Return compact persisted-deal summaries, newest first."""
        try:
            return await asyncio.to_thread(self._list_deals)
        except Exception as exc:
            logger.error("deal store list failed: %s", exc)
            return []


def get_deal_store(config: CreConfig | None = None) -> DealStore:
    """Build a lightweight store façade over the configured shared database."""
    return DealStore(config=config or CreConfig())


__all__ = ["DD_STATUSES", "DealStore", "get_deal_store"]
