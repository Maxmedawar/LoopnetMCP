"""Manual relationship-thread state and deterministic stall detection.

This module owns only ``rel_threads``.  Deal stage is read, when available, to
put higher-impact deals first; no deal-store row is created or changed here.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


AWAITING_PARTIES = frozenset({"us", "them"})
MANUAL_SUBSTRATE_NOTE = (
    "Thread state is manual/tool-fed evidence; direct email integration is later. "
    "A missing row does not prove that no reply is outstanding."
)

_STAGE_IMPACT: dict[str, tuple[int, str]] = {
    "closing": (100, "critical"),
    "financing": (95, "critical"),
    "diligence": (90, "high"),
    "under_contract": (90, "high"),
    "loi": (75, "high"),
    "contacted": (60, "medium"),
    "analyzing": (50, "medium"),
    "lead": (40, "medium"),
    "owned": (20, "low"),
    "passed": (0, "low"),
}


def _db_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None,
) -> Path:
    if isinstance(db_path, CreConfig):
        return db_path.cache_db_path.expanduser()
    if db_path is not None:
        return Path(db_path).expanduser()
    return (config or CreConfig()).cache_db_path.expanduser()


def _as_utc(value: Any = None, *, label: str) -> datetime:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{label} cannot be blank")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime") from exc
    else:
        raise ValueError(f"{label} must be a date, datetime, ISO string, or omitted")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_text(value: Any, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} is required")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


class RelationThreadStore:
    """Own the relationship-thread table in the shared SQLite database."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        self.db_path = _db_path(db_path, config)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS rel_threads (
                deal_id TEXT NOT NULL,
                counterparty TEXT NOT NULL,
                direction TEXT NOT NULL,
                topic TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                awaiting TEXT NOT NULL,
                note TEXT,
                PRIMARY KEY(deal_id, counterparty, topic),
                CHECK(awaiting IN ('us', 'them'))
            );
            CREATE INDEX IF NOT EXISTS idx_rel_threads_stalls
                ON rel_threads(awaiting, last_message_at, deal_id);
            """
        )
        return connection

    def record(
        self,
        deal_id: str,
        counterparty: str,
        direction: str,
        topic: str,
        last_message_at: Any,
        awaiting: str,
        note: str | None,
    ) -> dict[str, Any]:
        normalized_deal = _required_text(deal_id, "deal_id")
        normalized_counterparty = _required_text(counterparty, "counterparty")
        normalized_direction = _required_text(direction, "direction")
        normalized_topic = _required_text(topic, "topic")
        normalized_awaiting = _required_text(awaiting, "awaiting").casefold()
        if normalized_awaiting not in AWAITING_PARTIES:
            raise ValueError("awaiting must be us or them")
        timestamp = _as_utc(last_message_at, label="last_message_at").isoformat()
        normalized_note = None if note is None else str(note).strip() or None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rel_threads(
                    deal_id, counterparty, direction, topic,
                    last_message_at, awaiting, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id, counterparty, topic) DO UPDATE SET
                    direction=excluded.direction,
                    last_message_at=excluded.last_message_at,
                    awaiting=excluded.awaiting,
                    note=excluded.note
                """,
                (
                    normalized_deal,
                    normalized_counterparty,
                    normalized_direction,
                    normalized_topic,
                    timestamp,
                    normalized_awaiting,
                    normalized_note,
                ),
            )
        return {
            "deal_id": normalized_deal,
            "counterparty": normalized_counterparty,
            "direction": normalized_direction,
            "topic": normalized_topic,
            "last_message_at": timestamp,
            "awaiting": normalized_awaiting,
            "note": normalized_note,
            "who_owes_whom": (
                f"{normalized_counterparty} owes us an answer"
                if normalized_awaiting == "them"
                else f"We owe {normalized_counterparty} an answer"
            ),
            "recording_basis": MANUAL_SUBSTRATE_NOTE,
        }

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def stalled(self, days: int, as_of: datetime) -> list[dict[str, Any]]:
        cutoff = as_of - timedelta(days=days)
        with self._connect() as connection:
            has_deals = self._table_exists(connection, "deals")
            if has_deals:
                rows = connection.execute(
                    """
                    SELECT r.deal_id, r.counterparty, r.direction, r.topic,
                           r.last_message_at, r.awaiting, r.note, d.stage
                    FROM rel_threads r
                    LEFT JOIN deals d ON d.deal_id = r.deal_id
                    WHERE r.last_message_at <= ?
                    """,
                    (cutoff.isoformat(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT deal_id, counterparty, direction, topic,
                           last_message_at, awaiting, note, NULL AS stage
                    FROM rel_threads
                    WHERE last_message_at <= ?
                    """,
                    (cutoff.isoformat(),),
                ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            last_message = _as_utc(row["last_message_at"], label="last_message_at")
            stage = None if row["stage"] is None else str(row["stage"])
            impact_score, impact = _STAGE_IMPACT.get(
                (stage or "").casefold(),
                (30, "unclassified"),
            )
            elapsed = max(0, int((as_of - last_message).total_seconds() // 86400))
            counterparty = str(row["counterparty"])
            awaiting = str(row["awaiting"])
            results.append(
                {
                    "deal_id": str(row["deal_id"]),
                    "counterparty": counterparty,
                    "direction": str(row["direction"]),
                    "topic": str(row["topic"]),
                    "last_message_at": last_message.isoformat(),
                    "awaiting": awaiting,
                    "note": row["note"],
                    "who_owes_whom": (
                        f"{counterparty} owes us an answer"
                        if awaiting == "them"
                        else f"We owe {counterparty} an answer"
                    ),
                    "stalled_for_days": elapsed,
                    "deal_stage": stage,
                    "deal_impact": impact,
                    "deal_impact_score": impact_score,
                }
            )
        results.sort(
            key=lambda row: (
                -int(row["deal_impact_score"]),
                -int(row["stalled_for_days"]),
                str(row["deal_id"]).casefold(),
                str(row["counterparty"]).casefold(),
                str(row["topic"]).casefold(),
            )
        )
        return results


def record_thread_state(
    deal_id: str,
    counterparty: str,
    direction: str,
    topic: str,
    last_message_at: Any,
    awaiting: str,
    note: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Upsert the latest known state of one manually/tool-fed thread."""

    return RelationThreadStore(db_path, config=config).record(
        deal_id,
        counterparty,
        direction,
        topic,
        last_message_at,
        awaiting,
        note,
    )


def stalled_threads(
    days: int = 4,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Return threads at least ``days`` old, ordered by recorded deal impact."""

    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError("days must be a non-negative integer")
    report_as_of = _as_utc(as_of, label="as_of")
    rows = RelationThreadStore(db_path, config=config).stalled(days, report_as_of)
    return {
        "as_of": report_as_of.isoformat(),
        "threshold_days": days,
        "count": len(rows),
        "stalled_threads": rows,
        "sort": "deal impact descending, then stalled days descending",
        "honesty": MANUAL_SUBSTRATE_NOTE,
    }


__all__ = [
    "MANUAL_SUBSTRATE_NOTE",
    "RelationThreadStore",
    "record_thread_state",
    "stalled_threads",
]
