"""Persistent lender-reporting obligations and inclusive upcoming calendar."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


NON_ACTIONABLE_STATUSES = frozenset({"complete", "waived"})
KNOWN_STATUSES = frozenset(
    {"pending", "due", "open", "submitted", "complete", "waived", "overdue"}
)


def _text(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{label} cannot be blank")
    normalized = str(value).strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _day(value: Any, label: str, *, nullable: bool = False) -> date | None:
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{label} must be an ISO date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date") from exc
    raise ValueError(f"{label} must be an ISO date")


def _resolve_db_path(
    db_path: str | Path | CreConfig | None,
    config: CreConfig | None = None,
) -> Path:
    if isinstance(db_path, CreConfig):
        resolved = db_path.cache_db_path
    else:
        resolved = db_path or (config or CreConfig()).cache_db_path
    return Path(resolved).expanduser()


class ReportingStore:
    """Own only the ``fo_reporting`` table in the shared cache database."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        self.db_path = _resolve_db_path(db_path, config)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fo_reporting (
                loan TEXT NOT NULL,
                item TEXT NOT NULL,
                frequency TEXT,
                next_due TEXT,
                recipient TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY(loan, item)
            );
            CREATE INDEX IF NOT EXISTS idx_fo_reporting_due
                ON fo_reporting(next_due, loan, item);
            """
        )
        return connection

    def record(
        self,
        loan: str,
        item: str,
        frequency: str | None,
        next_due: date | datetime | str | None,
        recipient: str | None = None,
        status: str | None = "pending",
    ) -> dict[str, Any]:
        normalized_loan = _text(loan, "loan")
        normalized_item = _text(item, "item")
        normalized_frequency = _text(frequency, "frequency", nullable=True)
        due = _day(next_due, "next_due", nullable=True)
        normalized_recipient = _text(recipient, "recipient", nullable=True)
        normalized_status = _text(status or "pending", "status")
        assert normalized_loan is not None
        assert normalized_item is not None
        assert normalized_status is not None
        normalized_status = normalized_status.casefold()
        row = {
            "loan": normalized_loan,
            "item": normalized_item,
            "frequency": normalized_frequency,
            "next_due": due.isoformat() if due is not None else None,
            "recipient": normalized_recipient,
            "status": normalized_status,
        }
        with self._connect() as connection:
            existed = connection.execute(
                "SELECT 1 FROM fo_reporting WHERE loan=? AND item=?",
                (normalized_loan, normalized_item),
            ).fetchone() is not None
            connection.execute(
                """
                INSERT INTO fo_reporting(loan, item, frequency, next_due, recipient, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(loan, item) DO UPDATE SET
                    frequency=excluded.frequency,
                    next_due=excluded.next_due,
                    recipient=excluded.recipient,
                    status=excluded.status
                """,
                (
                    row["loan"],
                    row["item"],
                    row["frequency"],
                    row["next_due"],
                    row["recipient"],
                    row["status"],
                ),
            )
        unrecognized = []
        if normalized_status not in KNOWN_STATUSES:
            unrecognized.append(
                f"status {normalized_status!r} is stored but is outside the published status vocabulary"
            )
        return {
            **row,
            "record": row,
            "recorded": True,
            "operation": "updated" if existed else "inserted",
            "unrecognized_inputs": unrecognized,
        }

    def calendar(
        self,
        days: int | None = 60,
        *,
        as_of: date | datetime | str | None = None,
        loan: str | None = None,
    ) -> dict[str, Any]:
        window_days = 60 if days is None else days
        if isinstance(window_days, bool) or not isinstance(window_days, int) or window_days < 0:
            raise ValueError("days must be a non-negative integer")
        current = date.today() if as_of is None else _day(as_of, "as_of")
        assert current is not None
        through = current + timedelta(days=window_days)
        clauses = ["next_due >= ?", "next_due <= ?", "status NOT IN ('complete', 'waived')"]
        params: list[Any] = [current.isoformat(), through.isoformat()]
        normalized_loan = _text(loan, "loan", nullable=True)
        if normalized_loan is not None:
            clauses.append("loan = ?")
            params.append(normalized_loan)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT loan, item, frequency, next_due, recipient, status
                FROM fo_reporting
                WHERE {' AND '.join(clauses)}
                ORDER BY next_due, loan, item
                """,
                params,
            ).fetchall()
            undated = connection.execute(
                "SELECT COUNT(*) FROM fo_reporting WHERE next_due IS NULL"
                + (" AND loan = ?" if normalized_loan is not None else ""),
                ([normalized_loan] if normalized_loan is not None else []),
            ).fetchone()[0]
        deliverables = [dict(row) for row in rows]
        return {
            "as_of": current.isoformat(),
            "through": through.isoformat(),
            "days": window_days,
            "window_convention": "inclusive: as_of <= next_due <= as_of + days",
            "loan": normalized_loan,
            "deliverables": deliverables,
            "items": deliverables,
            "count": len(deliverables),
            "undated_items_excluded": int(undated),
            "excluded_statuses": sorted(NON_ACTIONABLE_STATUSES),
            "unrecognized_inputs": [],
        }


def record_reporting_item(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: date | datetime | str | None,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Insert or update one loan/item requirement."""

    return ReportingStore(db_path).record(
        loan,
        item,
        frequency,
        next_due,
        recipient,
        status,
    )


def record_reporting(
    loan: str,
    item: str,
    frequency: str | None,
    next_due: date | datetime | str | None,
    recipient: str | None = None,
    status: str | None = "pending",
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Compatibility alias for :func:`record_reporting_item`."""

    return record_reporting_item(
        loan,
        item,
        frequency,
        next_due,
        recipient,
        status,
        db_path,
    )


def reporting_calendar(
    days: int | None = 60,
    db_path: str | Path | CreConfig | None = None,
    as_of: date | datetime | str | None = None,
    loan: str | None = None,
) -> dict[str, Any]:
    """Return actionable deliverables due inside an inclusive look-ahead window."""

    return ReportingStore(db_path).calendar(days, as_of=as_of, loan=loan)


__all__ = [
    "KNOWN_STATUSES",
    "NON_ACTIONABLE_STATUSES",
    "ReportingStore",
    "record_reporting",
    "record_reporting_item",
    "reporting_calendar",
]
