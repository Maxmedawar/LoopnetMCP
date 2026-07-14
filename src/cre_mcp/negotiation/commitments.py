"""Durable negotiation commitments with an explicit status lifecycle."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


MADE_BY = frozenset({"us", "them"})
SOURCES = frozenset({"note", "call", "email"})
STATUSES = frozenset({"open", "kept", "broken", "superseded"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS neg_commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL,
    made_by TEXT NOT NULL,
    commitment TEXT NOT NULL,
    made_at TEXT NOT NULL,
    due TEXT,
    source TEXT NOT NULL DEFAULT 'note',
    status TEXT NOT NULL DEFAULT 'open',
    CHECK(made_by IN ('us', 'them')),
    CHECK(source IN ('note', 'call', 'email')),
    CHECK(status IN ('open', 'kept', 'broken', 'superseded'))
);
CREATE INDEX IF NOT EXISTS idx_neg_commitments_deal_status
    ON neg_commitments(deal_id, status, due, made_at, id);
"""


def _nonblank(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _timestamp(value: Any = None, *, name: str = "made_at") -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = _nonblank(value, name)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _due(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _nonblank(value, "due")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("due must be an ISO date") from exc


class CommitmentStore:
    """Own only ``neg_commitments`` in the shared cache database."""

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
        connection.executescript(_SCHEMA)
        return connection

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def record_commitment_note(
        self,
        deal_id: str,
        text: str,
        made_by: str,
        due: Any = None,
        *,
        source: str = "note",
        made_at: Any = None,
    ) -> dict[str, Any]:
        normalized_deal = _nonblank(deal_id, "deal_id")
        commitment = _nonblank(text, "text")
        normalized_made_by = _nonblank(made_by, "made_by").casefold()
        normalized_source = _nonblank(source, "source").casefold()
        if normalized_made_by not in MADE_BY:
            raise ValueError("made_by must be 'us' or 'them'")
        if normalized_source not in SOURCES:
            raise ValueError("source must be 'note', 'call', or 'email'")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO neg_commitments(
                    deal_id, made_by, commitment, made_at, due, source, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    normalized_deal,
                    normalized_made_by,
                    commitment,
                    _timestamp(made_at),
                    _due(due),
                    normalized_source,
                ),
            )
            row = connection.execute(
                "SELECT * FROM neg_commitments WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return self._row(row)

    def list_commitments(
        self, deal_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        normalized_deal = _nonblank(deal_id, "deal_id")
        params: list[Any] = [normalized_deal]
        where = "deal_id=?"
        if status is not None:
            normalized_status = _nonblank(status, "status").casefold()
            if normalized_status not in STATUSES:
                raise ValueError("invalid commitment status")
            where += " AND status=?"
            params.append(normalized_status)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM neg_commitments WHERE {where}
                ORDER BY made_at ASC, id ASC
                """,
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def open_commitments(self, deal_id: str) -> list[dict[str, Any]]:
        return self.list_commitments(deal_id, status="open")

    def update_commitment_status(self, commitment_id: int, status: str) -> dict[str, Any]:
        if isinstance(commitment_id, bool) or not isinstance(commitment_id, int):
            raise TypeError("commitment_id must be an integer")
        normalized_status = _nonblank(status, "status").casefold()
        if normalized_status not in STATUSES - {"open"}:
            raise ValueError("status transition must be kept, broken, or superseded")
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM neg_commitments WHERE id=?", (commitment_id,)
            ).fetchone()
            if current is None:
                raise KeyError(f"commitment {commitment_id} not found")
            if current["status"] == normalized_status:
                return self._row(current)
            if current["status"] != "open":
                raise ValueError(
                    f"commitment is already final as {current['status']}; final history is not rewritten"
                )
            connection.execute(
                "UPDATE neg_commitments SET status=? WHERE id=? AND status='open'",
                (normalized_status, commitment_id),
            )
            row = connection.execute(
                "SELECT * FROM neg_commitments WHERE id=?", (commitment_id,)
            ).fetchone()
        return self._row(row)

    def broken_commitment_counter(
        self, deal_id: str, *, made_by: str | None = None
    ) -> dict[str, Any]:
        normalized_deal = _nonblank(deal_id, "deal_id")
        normalized_made_by = None
        if made_by is not None:
            normalized_made_by = _nonblank(made_by, "made_by").casefold()
            if normalized_made_by not in MADE_BY:
                raise ValueError("made_by must be 'us' or 'them'")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT made_by, COUNT(*) AS count
                FROM neg_commitments
                WHERE deal_id=? AND status='broken'
                GROUP BY made_by ORDER BY made_by
                """,
                (normalized_deal,),
            ).fetchall()
        counts = {"us": 0, "them": 0}
        counts.update({row["made_by"]: row["count"] for row in rows})
        selected_count = (
            counts[normalized_made_by]
            if normalized_made_by is not None
            else counts["us"] + counts["them"]
        )
        return {
            "deal_id": normalized_deal,
            "made_by": normalized_made_by or "both",
            "broken_count": selected_count,
            "broken_commitments": counts["us"] + counts["them"],
            "counterparty_broken_commitments": counts["them"],
            "by_made_by": counts,
            "counterparty_credibility": {
                "label": "inference",
                "conduct_evidence": (
                    f"{counts['them']} tracked commitment(s) made by them are marked broken "
                    f"for deal {normalized_deal}."
                ),
                "interpretation": (
                    "Potential credibility concern; commitment status is conduct evidence, "
                    "not proof of intent or a calibrated score."
                ),
            },
            "counterparty_track_record_cross_link": (
                "Review beside cre_mcp.ledger.counterparty_track_record claim accuracy. "
                "This counter does not write to or alter that append-only claim ledger."
            ),
        }


def record_commitment_note(
    deal_id: str,
    text: str,
    made_by: str,
    due: Any = None,
    *,
    source: str = "note",
    made_at: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return CommitmentStore(db_path, config=config).record_commitment_note(
        deal_id, text, made_by, due, source=source, made_at=made_at
    )


def list_commitments(
    deal_id: str,
    *,
    status: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> list[dict[str, Any]]:
    return CommitmentStore(db_path, config=config).list_commitments(deal_id, status=status)


def open_commitments(
    deal_id: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> list[dict[str, Any]]:
    return CommitmentStore(db_path, config=config).open_commitments(deal_id)


def update_commitment_status(
    commitment_id: int,
    status: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return CommitmentStore(db_path, config=config).update_commitment_status(
        commitment_id, status
    )


def broken_commitment_counter(
    deal_id: str,
    *,
    made_by: str | None = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return CommitmentStore(db_path, config=config).broken_commitment_counter(
        deal_id, made_by=made_by
    )


__all__ = [
    "CommitmentStore",
    "broken_commitment_counter",
    "list_commitments",
    "open_commitments",
    "record_commitment_note",
    "update_commitment_status",
]
