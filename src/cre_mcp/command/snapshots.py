"""Durable listing snapshots and deterministic change events."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from cre_mcp.config import CreConfig

from ._db import resolve_db_path
from ._time import as_datetime

DOM_MILESTONES = (30, 60, 90, 120, 180, 365)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _listing_key(listing: dict[str, Any]) -> str:
    explicit = str(listing.get("listing_key") or "").strip()
    if explicit:
        return explicit
    source = str(listing.get("source") or "").strip()
    source_id = str(listing.get("source_id") or "").strip()
    if source and source_id:
        return f"{source}:{source_id}"
    url = str(listing.get("url") or "").strip()
    if url:
        return f"url:{url.casefold()}"
    raise ValueError("listing requires listing_key, source+source_id, or url")


class SnapshotStore:
    """Own the isolated ``listing_snapshots`` table in the shared cache database."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        self.db_path = resolve_db_path(db_path or config)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS listing_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_key TEXT NOT NULL,
                deal_id TEXT,
                price REAL,
                status TEXT,
                dom INTEGER,
                broker TEXT,
                raw_json TEXT NOT NULL,
                captured_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_listing_snapshots_key_time
                ON listing_snapshots(listing_key, captured_at, snapshot_id);
            """
        )
        return connection

    def record_snapshot(self, listing: dict[str, Any]) -> dict[str, Any]:
        """Persist one normalized snapshot while retaining the full raw payload."""
        if not isinstance(listing, dict):
            raise ValueError("listing must be a dictionary")
        listing_key = _listing_key(listing)
        deal_id_value = listing.get("deal_id")
        deal_id = str(deal_id_value).strip() if deal_id_value is not None else None
        deal_id = deal_id or None
        price = _first_number(
            listing.get("price"),
            listing.get("price_usd"),
            listing.get("asking_price"),
        )
        status_value = listing.get("status", listing.get("listing_status"))
        status = str(status_value).strip() if status_value is not None else None
        status = status or None
        dom = _integer(listing.get("dom", listing.get("days_on_market")))
        broker_value = listing.get("broker", listing.get("broker_name"))
        broker = str(broker_value).strip() if broker_value is not None else None
        broker = broker or None
        captured_value = listing.get("captured_at")
        captured = (
            as_datetime(captured_value)
            if captured_value is not None
            else datetime.now(UTC)
        )
        raw_json = json.dumps(listing, separators=(",", ":"), sort_keys=True, default=str)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO listing_snapshots(
                    listing_key, deal_id, price, status, dom, broker,
                    raw_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_key,
                    deal_id,
                    price,
                    status,
                    dom,
                    broker,
                    raw_json,
                    captured.isoformat(),
                ),
            )
        return {
            "snapshot_id": int(cursor.lastrowid),
            "listing_key": listing_key,
            "deal_id": deal_id,
            "price": price,
            "status": status,
            "dom": dom,
            "broker": broker,
            "raw": dict(listing),
            "captured_at": captured.isoformat(),
        }

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "snapshot_id": int(row["snapshot_id"]),
            "listing_key": row["listing_key"],
            "deal_id": row["deal_id"],
            "price": row["price"],
            "status": row["status"],
            "dom": row["dom"],
            "broker": row["broker"],
            "raw": json.loads(str(row["raw_json"])),
            "captured_at": row["captured_at"],
        }

    def list_snapshots(self, listing_key: str) -> list[dict[str, Any]]:
        """Return one listing's snapshots in stable chronological order."""
        normalized = listing_key.strip()
        if not normalized:
            raise ValueError("listing_key cannot be blank")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_id, listing_key, deal_id, price, status,
                       dom, broker, raw_json, captured_at
                FROM listing_snapshots
                WHERE listing_key = ?
                ORDER BY captured_at, snapshot_id
                """,
                (normalized,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def listing_keys(self) -> list[str]:
        """Return all snapshotted listing keys deterministically."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT listing_key FROM listing_snapshots ORDER BY listing_key"
            ).fetchall()
        return [str(row["listing_key"]) for row in rows]

    def diff_snapshots(self, listing_key: str) -> list[dict[str, Any]]:
        """Return normalized change events between every consecutive snapshot."""
        return changes_from_snapshots(self.list_snapshots(listing_key))


def changes_from_snapshots(
    snapshots: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute listing change events without performing database I/O."""
    ordered = sorted(
        (dict(snapshot) for snapshot in snapshots),
        key=lambda item: (str(item.get("captured_at") or ""), int(item.get("snapshot_id") or 0)),
    )
    events: list[dict[str, Any]] = []
    for previous, current in zip(ordered, ordered[1:]):
        base = {
            "listing_key": current.get("listing_key") or previous.get("listing_key"),
            "deal_id": current.get("deal_id") or previous.get("deal_id"),
            "previous_captured_at": previous.get("captured_at"),
            "captured_at": current.get("captured_at"),
            "from_snapshot_id": previous.get("snapshot_id"),
            "to_snapshot_id": current.get("snapshot_id"),
        }
        old_price = _number(previous.get("price"))
        new_price = _number(current.get("price"))
        if old_price is not None and new_price is not None and old_price != new_price:
            pct_change = round(((new_price - old_price) / old_price) * 100, 2) if old_price else None
            events.append(
                {
                    **base,
                    "event_type": "price_change",
                    "from": old_price,
                    "to": new_price,
                    "direction": "decrease" if new_price < old_price else "increase",
                    "pct_change": pct_change,
                }
            )
        old_status = previous.get("status")
        new_status = current.get("status")
        if (
            old_status is not None
            and new_status is not None
            and str(old_status).strip().casefold() != str(new_status).strip().casefold()
        ):
            events.append(
                {
                    **base,
                    "event_type": "status_change",
                    "from": old_status,
                    "to": new_status,
                }
            )
        old_broker = previous.get("broker")
        new_broker = current.get("broker")
        if (
            old_broker is not None
            and new_broker is not None
            and str(old_broker).strip().casefold() != str(new_broker).strip().casefold()
        ):
            events.append(
                {
                    **base,
                    "event_type": "broker_change",
                    "from": old_broker,
                    "to": new_broker,
                }
            )
        old_dom = _integer(previous.get("dom"))
        new_dom = _integer(current.get("dom"))
        if old_dom is not None and new_dom is not None and new_dom > old_dom:
            for milestone in DOM_MILESTONES:
                if old_dom < milestone <= new_dom:
                    events.append(
                        {
                            **base,
                            "event_type": "dom_milestone",
                            "from": old_dom,
                            "to": new_dom,
                            "milestone_days": milestone,
                        }
                    )
    event_order = {
        "price_change": 0,
        "status_change": 1,
        "broker_change": 2,
        "dom_milestone": 3,
    }
    events.sort(
        key=lambda event: (
            str(event.get("captured_at") or ""),
            str(event.get("listing_key") or ""),
            event_order.get(str(event.get("event_type")), 99),
            int(event.get("milestone_days") or 0),
        )
    )
    return events


def record_snapshot(
    listing: dict[str, Any],
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Persist one listing snapshot in the configured cache database."""
    return SnapshotStore(db_path).record_snapshot(listing)


def diff_snapshots(
    listing_key: str,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> list[dict[str, Any]]:
    """Return all persisted changes for one listing key."""
    return SnapshotStore(db_path).diff_snapshots(listing_key)


__all__ = [
    "DOM_MILESTONES",
    "SnapshotStore",
    "changes_from_snapshots",
    "diff_snapshots",
    "record_snapshot",
]
