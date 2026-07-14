"""Append-only approvals for nonstandard negotiated terms."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


_SCHEMA = """
CREATE TABLE IF NOT EXISTS neg_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL,
    term TEXT NOT NULL,
    standard_value TEXT,
    approved_value TEXT,
    approved_by TEXT NOT NULL,
    why TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_neg_approvals_deal_at
    ON neg_approvals(deal_id, at, id);
CREATE TRIGGER IF NOT EXISTS neg_approvals_no_update
BEFORE UPDATE ON neg_approvals
BEGIN
    SELECT RAISE(ABORT, 'neg_approvals is append-only');
END;
CREATE TRIGGER IF NOT EXISTS neg_approvals_no_delete
BEFORE DELETE ON neg_approvals
BEGIN
    SELECT RAISE(ABORT, 'neg_approvals is append-only');
END;
"""


def _nonblank(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _timestamp(value: Any = None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = _nonblank(value, "at")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("at must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _decode(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


class ApprovalStore:
    """Own only ``neg_approvals`` and forbid update/delete at the DB boundary."""

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
        result = dict(row)
        result["standard_value"] = _decode(result["standard_value"])
        result["approved_value"] = _decode(result["approved_value"])
        return result

    def record_term_approval(
        self,
        deal_id: str,
        term: str,
        standard_value: Any,
        approved_value: Any,
        approved_by: str,
        why: str,
        *,
        at: Any = None,
    ) -> dict[str, Any]:
        values = (
            _nonblank(deal_id, "deal_id"),
            _nonblank(term, "term"),
            _encode(standard_value),
            _encode(approved_value),
            _nonblank(approved_by, "approved_by"),
            _nonblank(why, "why"),
            _timestamp(at),
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO neg_approvals(
                    deal_id, term, standard_value, approved_value,
                    approved_by, why, at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = connection.execute(
                "SELECT * FROM neg_approvals WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return self._row(row)

    def list_approvals(self, deal_id: str) -> list[dict[str, Any]]:
        normalized_deal = _nonblank(deal_id, "deal_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM neg_approvals
                WHERE deal_id=? ORDER BY at ASC, id ASC
                """,
                (normalized_deal,),
            ).fetchall()
        return [self._row(row) for row in rows]


def record_term_approval(
    deal_id: str,
    term: str,
    standard_value: Any,
    approved_value: Any,
    approved_by: str,
    why: str,
    *,
    at: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    return ApprovalStore(db_path, config=config).record_term_approval(
        deal_id,
        term,
        standard_value,
        approved_value,
        approved_by,
        why,
        at=at,
    )


def list_approvals(
    deal_id: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> list[dict[str, Any]]:
    return ApprovalStore(db_path, config=config).list_approvals(deal_id)


__all__ = ["ApprovalStore", "list_approvals", "record_term_approval"]
