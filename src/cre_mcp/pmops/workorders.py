"""Durable property-management work orders and transparent triage.

Only ``pm_workorders`` is owned here.  The priority model is deliberately a
lexicographic convention: an open life-safety order is always ahead of every
non-life-safety order, regardless of cost or due date.  Scores are displayed
for auditability but never override that gate.
"""

from __future__ import annotations

import calendar
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.config import CreConfig


SEVERITIES = frozenset({"life_safety", "tenant_impact", "routine"})
TERMINAL_STATUSES = frozenset(
    {"cancelled", "closed", "complete", "completed", "done", "resolved"}
)
REPEAT_THRESHOLD = 3
REPEAT_WINDOW_MONTHS = 12

# Scores explain priority within the hard lexicographic bands.  They do not
# determine whether a row crosses the life-safety, overdue, or repeat gates.
TRIAGE_WEIGHTS: dict[str, int] = {
    "life_safety": 100,
    "tenant_impact": 30,
    "routine": 10,
    "sla_overdue": 40,
    "repeat_offender_system": 20,
    "cost_per_1000_dollars": 1,
    "cost_points_cap": 25,
}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _normalize_system(value: Any) -> str:
    return _required_text(value, "system").casefold().replace("-", "_").replace(" ", "_")


def _iso_date(value: date | datetime | str | None, name: str, *, nullable: bool) -> str | None:
    if value is None:
        if nullable:
            return None
        raise ValueError(f"{name} is required")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _as_of(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    normalized = _iso_date(value, "as_of", nullable=False)
    assert normalized is not None
    return date.fromisoformat(normalized)


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _cents(value: Any, name: str = "cost_cents") -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents when provided")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


class WorkOrderStore:
    """Own and query work orders in the shared CRE cache database."""

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
        """Open a transaction and initialize only ``pm_workorders``."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pm_workorders (
                workorder_id TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                unit TEXT,
                system TEXT NOT NULL,
                description TEXT NOT NULL,
                opened TEXT NOT NULL,
                due TEXT,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                cost_cents INTEGER,
                vendor TEXT,
                CHECK(severity IN ('life_safety', 'tenant_impact', 'routine')),
                CHECK(cost_cents IS NULL OR cost_cents >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_pm_workorders_queue
                ON pm_workorders(status, severity, due, opened, workorder_id);
            CREATE INDEX IF NOT EXISTS idx_pm_workorders_repeat
                ON pm_workorders(asset, system, opened, workorder_id);
            CREATE INDEX IF NOT EXISTS idx_pm_workorders_vendor
                ON pm_workorders(vendor, opened, workorder_id);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_workorder(
        self,
        asset: str,
        system: str,
        description: str,
        opened: date | datetime | str,
        severity: str,
        status: str,
        unit: str | None = None,
        due: date | datetime | str | None = None,
        cost_cents: int | None = None,
        vendor: str | None = None,
        workorder_id: str | None = None,
    ) -> dict[str, Any]:
        """Record one work order without silently accepting undeclared fields."""

        normalized_severity = _required_text(severity, "severity").casefold()
        if normalized_severity not in SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(sorted(SEVERITIES))}")
        normalized_status = _required_text(status, "status").casefold()
        opened_text = _iso_date(opened, "opened", nullable=False)
        assert opened_text is not None
        due_text = _iso_date(due, "due", nullable=True)
        if due_text is not None and due_text < opened_text:
            raise ValueError("due cannot be earlier than opened")
        normalized_id = _optional_text(workorder_id, "workorder_id")
        normalized_id = normalized_id or f"pmwo-{uuid.uuid4().hex}"
        values = (
            normalized_id,
            _required_text(asset, "asset"),
            _optional_text(unit, "unit"),
            _normalize_system(system),
            _required_text(description, "description"),
            opened_text,
            due_text,
            normalized_severity,
            normalized_status,
            _cents(cost_cents),
            _optional_text(vendor, "vendor"),
        )
        try:
            with self.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO pm_workorders(
                        workorder_id, asset, unit, system, description, opened,
                        due, severity, status, cost_cents, vendor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM pm_workorders WHERE workorder_id=?",
                    (normalized_id,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"workorder_id already exists: {normalized_id}") from exc
        if row is None:
            raise RuntimeError("work-order insert did not produce a durable row")
        result = dict(row)
        result["source_ref"] = {
            "table": "pm_workorders",
            "primary_key": normalized_id,
            "database": str(self.db_path),
        }
        return result

    def list_workorders(
        self,
        *,
        asset: str | None = None,
        system: str | None = None,
        opened_from: date | datetime | str | None = None,
        opened_to: date | datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if asset is not None:
            clauses.append("asset=?")
            values.append(_required_text(asset, "asset"))
        if system is not None:
            clauses.append("system=?")
            values.append(_normalize_system(system))
        if opened_from is not None:
            clauses.append("opened>=?")
            values.append(_iso_date(opened_from, "opened_from", nullable=False))
        if opened_to is not None:
            clauses.append("opened<=?")
            values.append(_iso_date(opened_to, "opened_to", nullable=False))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM pm_workorders {where}
                ORDER BY opened, workorder_id
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def triage_queue(
        self,
        as_of: date | datetime | str | None = None,
        asset: str | None = None,
    ) -> dict[str, Any]:
        """Rank active orders using non-negotiable safety and SLA gates."""

        on_date = _as_of(as_of)
        repeat_start = _subtract_months(on_date, REPEAT_WINDOW_MONTHS)
        all_rows = self.list_workorders(opened_to=on_date)
        repeat_counts: dict[tuple[str, str], int] = {}
        for row in all_rows:
            opened_date = date.fromisoformat(str(row["opened"]))
            if repeat_start <= opened_date <= on_date:
                key = (str(row["asset"]), str(row["system"]))
                repeat_counts[key] = repeat_counts.get(key, 0) + 1

        normalized_asset = _required_text(asset, "asset") if asset is not None else None
        queue: list[dict[str, Any]] = []
        for raw in all_rows:
            if normalized_asset is not None and raw["asset"] != normalized_asset:
                continue
            if str(raw["status"]).casefold() in TERMINAL_STATUSES:
                continue
            row = dict(raw)
            due_date = date.fromisoformat(str(row["due"])) if row["due"] else None
            overdue = due_date is not None and due_date < on_date
            days_overdue = (on_date - due_date).days if overdue and due_date else 0
            system_count = repeat_counts.get((str(row["asset"]), str(row["system"])), 0)
            repeat_offender = system_count >= REPEAT_THRESHOLD
            cost_points = min(
                int(row["cost_cents"] or 0) // 100_000,
                TRIAGE_WEIGHTS["cost_points_cap"],
            )
            score = (
                TRIAGE_WEIGHTS[str(row["severity"])]
                + (TRIAGE_WEIGHTS["sla_overdue"] if overdue else 0)
                + (TRIAGE_WEIGHTS["repeat_offender_system"] if repeat_offender else 0)
                + cost_points * TRIAGE_WEIGHTS["cost_per_1000_dollars"]
            )
            row.update(
                {
                    "is_life_safety_gate": row["severity"] == "life_safety",
                    "sla_overdue": overdue,
                    "sla_days_overdue": days_overdue,
                    "system_orders_12mo": system_count,
                    "repeat_offender_system": repeat_offender,
                    "convention_score": score,
                    "score_arithmetic": {
                        "severity_points": TRIAGE_WEIGHTS[str(row["severity"])],
                        "sla_overdue_points": TRIAGE_WEIGHTS["sla_overdue"] if overdue else 0,
                        "repeat_points": (
                            TRIAGE_WEIGHTS["repeat_offender_system"] if repeat_offender else 0
                        ),
                        "cost_points": cost_points,
                    },
                }
            )
            queue.append(row)

        # The first three keys are hard priority bands.  The displayed score is
        # only a within-band tie-breaker, so no amount of cost can cross a gate.
        queue.sort(
            key=lambda row: (
                not bool(row["is_life_safety_gate"]),
                not bool(row["sla_overdue"]),
                not bool(row["repeat_offender_system"]),
                -int(row["convention_score"]),
                str(row["opened"]),
                str(row["workorder_id"]),
            )
        )
        for index, row in enumerate(queue, start=1):
            row["triage_rank"] = index

        return {
            "as_of": on_date.isoformat(),
            "queue": queue,
            "queue_count": len(queue),
            "conventions": {
                "ranking_order": [
                    "life_safety_first_unconditional",
                    "sla_overdue_first",
                    "repeat_offender_system_first",
                    "convention_score_descending",
                    "oldest_opened_first",
                ],
                "weights": dict(TRIAGE_WEIGHTS),
                "repeat_threshold_orders": REPEAT_THRESHOLD,
                "repeat_window_months": REPEAT_WINDOW_MONTHS,
                "repeat_grouping": "asset + system",
                "sla_overdue_definition": "active order due date is earlier than as_of",
                "terminal_statuses_excluded": sorted(TERMINAL_STATUSES),
                "cost_score_definition": (
                    "floor(cost_cents / 100000) points, capped; $1,000 equals 100000 cents"
                ),
                "severity_is_convention": True,
            },
        }


def record_workorder(
    asset: str,
    system: str,
    description: str,
    opened: date | datetime | str,
    severity: str,
    status: str,
    unit: str | None = None,
    due: date | datetime | str | None = None,
    cost_cents: int | None = None,
    vendor: str | None = None,
    workorder_id: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Record a work order through a short-lived store."""

    return WorkOrderStore(db_path).record_workorder(
        asset,
        system,
        description,
        opened,
        severity,
        status,
        unit,
        due,
        cost_cents,
        vendor,
        workorder_id,
    )


def triage_queue(
    as_of: date | datetime | str | None = None,
    asset: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Return the active work-order triage queue."""

    return WorkOrderStore(db_path).triage_queue(as_of, asset)


__all__ = [
    "REPEAT_THRESHOLD",
    "REPEAT_WINDOW_MONTHS",
    "SEVERITIES",
    "TERMINAL_STATUSES",
    "TRIAGE_WEIGHTS",
    "WorkOrderStore",
    "record_workorder",
    "triage_queue",
]
