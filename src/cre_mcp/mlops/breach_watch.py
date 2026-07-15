"""Durable watch items for owner-side master-lease default exposure.

The master tenant sits between the owner and each subtenant.  A subtenant's
payment, insurance, maintenance, or use failure can therefore become the
master tenant's default even when the master tenant did not cause the original
problem.  This module owns only the ``ml_watch`` table and keeps that sandwich
risk visible.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.config import CreConfig

WATCH_ITEMS = frozenset(
    {
        "coi_expiry",
        "insurance_lapse",
        "maintenance",
        "use_violation",
        "payment_late",
    }
)
SEVERITIES = frozenset({"low", "medium", "high", "critical"})
WATCH_STATUSES = frozenset(
    {
        "open",
        "pending",
        "monitoring",
        "cure_in_progress",
        "cured",
        "resolved",
        "waived",
        "closed",
    }
)
RESOLVED_STATUSES = frozenset({"cured", "resolved", "waived", "closed"})

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_TRIGGER_RANK = {
    "insurance_lapse": 5,
    "payment_late": 4,
    "use_violation": 3,
    "maintenance": 2,
    "coi_expiry": 1,
}
_SANDWICH_PATH = {
    "coi_expiry": (
        "Expired proof of insurance can conceal a lapse or breach a document-delivery "
        "covenant; the master tenant may have to produce evidence or cure regardless of "
        "the subtenant's cooperation."
    ),
    "insurance_lapse": (
        "A subtenant coverage lapse can leave the premises uninsured and put the master "
        "tenant in breach of the master lease's insurance covenants."
    ),
    "maintenance": (
        "Uncured subtenant maintenance can become the master tenant's repair obligation, "
        "owner cure charge, or default."
    ),
    "use_violation": (
        "A subtenant's prohibited or unlawful use can trigger owner remedies against the "
        "master tenant even when the master tenant did not perform the use."
    ),
    "payment_late": (
        "Subtenant nonpayment does not suspend master rent; the master tenant must fund "
        "the shortfall or risk an owner-side payment default."
    ),
}


def _text(value: Any, *, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} cannot be blank")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _choice(value: Any, *, name: str, allowed: frozenset[str]) -> str:
    normalized = _text(value, name=name).casefold()
    if normalized not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _iso_temporal(value: Any, *, name: str, nullable: bool) -> str | None:
    """Normalize an ISO date/datetime without inventing a missing deadline."""

    if value is None:
        if nullable:
            return None
        raise ValueError(f"{name} must be an ISO date or datetime")
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an ISO date or datetime")
    if isinstance(value, datetime):
        parsed_datetime = value
        if parsed_datetime.tzinfo is not None:
            parsed_datetime = parsed_datetime.astimezone(UTC)
        return parsed_datetime.isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw = str(value).strip()
    if not raw:
        if nullable:
            return None
        raise ValueError(f"{name} must be an ISO date or datetime")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    try:
        parsed_datetime = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date or datetime") from exc
    if parsed_datetime.tzinfo is not None:
        parsed_datetime = parsed_datetime.astimezone(UTC)
    return parsed_datetime.isoformat()


def _calendar_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _as_of_date(value: Any = None) -> date:
    if value is None:
        return date.today()
    normalized = _iso_temporal(value, name="as_of", nullable=False)
    assert normalized is not None
    return _calendar_date(normalized)


class WatchStore:
    """Own the master-lease breach-watch rows in the shared cache database."""

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

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction and initialize only the table owned here."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ml_watch (
                watch_id TEXT PRIMARY KEY,
                position_id TEXT NOT NULL,
                item TEXT NOT NULL,
                due_or_observed TEXT,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                CHECK(item IN (
                    'coi_expiry', 'insurance_lapse', 'maintenance',
                    'use_violation', 'payment_late'
                )),
                CHECK(severity IN ('low', 'medium', 'high', 'critical')),
                CHECK(status IN (
                    'open', 'pending', 'monitoring', 'cure_in_progress',
                    'cured', 'resolved', 'waived', 'closed'
                ))
            );
            CREATE INDEX IF NOT EXISTS idx_ml_watch_position
                ON ml_watch(position_id, status, due_or_observed, severity, watch_id);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_watch_item(
        self,
        position_id: str,
        item: str,
        due_or_observed: Any,
        severity: str,
        status: str,
        *,
        watch_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one watch item; repeated item types are intentionally preserved."""

        normalized_id = _text(position_id, name="position_id")
        normalized_item = _choice(item, name="item", allowed=WATCH_ITEMS)
        normalized_severity = _choice(
            severity, name="severity", allowed=SEVERITIES
        )
        normalized_status = _choice(
            status, name="status", allowed=WATCH_STATUSES
        )
        normalized_date = _iso_temporal(
            due_or_observed, name="due_or_observed", nullable=True
        )
        normalized_watch_id = (
            _text(watch_id, name="watch_id")
            if watch_id is not None
            else f"mlw-{uuid.uuid4().hex}"
        )
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO ml_watch(
                    watch_id, position_id, item, due_or_observed,
                    severity, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_watch_id,
                    normalized_id,
                    normalized_item,
                    normalized_date,
                    normalized_severity,
                    normalized_status,
                ),
            )
            row = connection.execute(
                "SELECT * FROM ml_watch WHERE watch_id=?",
                (normalized_watch_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("watch-item insert did not produce a durable row")
        return dict(row)

    def list_watch_items(self, position_id: str) -> list[dict[str, Any]]:
        normalized_id = _text(position_id, name="position_id")
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT watch_id, position_id, item, due_or_observed,
                       severity, status
                FROM ml_watch
                WHERE position_id=?
                ORDER BY watch_id
                """,
                (normalized_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def record_watch_item(
    position_id: str,
    item: str,
    due_or_observed: Any,
    severity: str,
    status: str,
    *,
    db_path: str | Path | None = None,
    watch_id: str | None = None,
) -> dict[str, Any]:
    """Record a durable breach-watch item using an explicit, FastMCP-safe surface."""

    return WatchStore(db_path).record_watch_item(
        position_id,
        item,
        due_or_observed,
        severity,
        status,
        watch_id=watch_id,
    )


def _enrich(row: dict[str, Any], as_of: date) -> dict[str, Any]:
    enriched = dict(row)
    raw_date = row.get("due_or_observed")
    days = (_calendar_date(raw_date) - as_of).days if raw_date else None
    enriched["days_to_consequence"] = days
    if days is None:
        urgency = "unknown_date"
    elif days < 0:
        urgency = "overdue_or_already_observed"
    elif days == 0:
        urgency = "due_or_observed_today"
    elif days <= 7:
        urgency = "within_7_days"
    elif days <= 30:
        urgency = "within_30_days"
    else:
        urgency = "scheduled_beyond_30_days"
    enriched["urgency"] = urgency
    enriched["sandwich_path"] = _SANDWICH_PATH[str(row["item"])]
    enriched["date_basis"] = (
        "The supplied date is used as the consequence-ordering proxy. For an observed "
        "condition it may be an observation date, not a contractual cure deadline."
    )
    return enriched


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    days = row.get("days_to_consequence")
    sortable_days = 10**9 if days is None else int(days)
    severity_rank = _SEVERITY_RANK[str(row["severity"])]
    trigger_rank = _TRIGGER_RANK[str(row["item"])]
    return sortable_days, -severity_rank, -trigger_rank, str(row["watch_id"])


def breach_report(
    position_id: str,
    *,
    as_of: Any = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Report open sandwich-risk items in consequence order.

    Dates are sorted ascending, then severity descending.  A past observation
    sorts ahead of future deadlines because it may already require investigation
    or cure; this ordering is triage, not a legal default determination.
    """

    normalized_id = _text(position_id, name="position_id")
    report_date = _as_of_date(as_of)
    rows = WatchStore(db_path).list_watch_items(normalized_id)
    active = [
        _enrich(row, report_date)
        for row in rows
        if row["status"] not in RESOLVED_STATUSES
    ]
    resolved = [
        _enrich(row, report_date)
        for row in rows
        if row["status"] in RESOLVED_STATUSES
    ]
    active.sort(key=_sort_key)
    resolved.sort(key=_sort_key)
    dated_active = [item for item in active if item["days_to_consequence"] is not None]
    past_or_current = [
        item for item in dated_active if int(item["days_to_consequence"]) <= 0
    ]
    highest = (
        max(active, key=lambda item: _SEVERITY_RANK[str(item["severity"])])[
            "severity"
        ]
        if active
        else None
    )
    unknown_dates = sum(item["days_to_consequence"] is None for item in active)

    return {
        "rent_owed_vs_received_exposure": {
            "master_rent_owed_cents": None,
            "sublease_received_cents": None,
            "uncovered_exposure_cents": None,
            "negative_carry_warning": (
                "Master rent continues even when a subtenant breach stops or delays "
                "sublease receipts. This watch API has no control period, so it does not "
                "invent the rent amounts."
            ),
            "route": (
                "Call cre_mcp.mlops.control_books.position_status (or the "
                "ml_position_status tool) with position_id and period for penny-exact "
                "rent owed versus rent received."
            ),
        },
        "owner_side_default_exposure": {
            "risk": (
                "Sandwich risk: a subtenant breach can become the master tenant's "
                "owner-side default, while master rent and cure duties continue."
            ),
            "active_trigger_count": len(active),
            "past_due_or_already_observed_count": len(past_or_current),
            "highest_active_severity": highest,
        },
        "position_id": normalized_id,
        "as_of": report_date.isoformat(),
        "items": active,
        "resolved_items": resolved,
        "item_count": len(active),
        "resolved_item_count": len(resolved),
        "honesty": {
            "posture": (
                "Operational triage only; no item is classified as a legal default, "
                "waiver, cure, or enforceable remedy."
            ),
            "ordering": (
                "Active items sort by days to the supplied due/observed date, then "
                "severity, then trigger convention."
            ),
            "unknown_consequence_dates": unknown_dates,
            "date_gap": (
                "An observation date is not necessarily a lease notice or cure deadline. "
                "Confirm notice, grace, and cure periods from the signed documents."
            ),
            "counsel_review_required": True,
        },
    }


__all__ = [
    "WATCH_ITEMS",
    "SEVERITIES",
    "WATCH_STATUSES",
    "WatchStore",
    "record_watch_item",
    "breach_report",
]
