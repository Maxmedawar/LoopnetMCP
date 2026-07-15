"""Vendor registry and comparisons constrained to recorded work-order history.

Only ``pm_vendors`` is owned here.  Work-order observations are read from the
``pm_workorders`` table when it already exists; no synthetic prices, response
times, or quality scores are introduced for vendors without history.
"""

from __future__ import annotations

import calendar
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from cre_mcp.config import CreConfig


_TERMINAL_STATUSES = frozenset(
    {"cancelled", "closed", "complete", "completed", "done", "resolved"}
)
_REPEAT_LOOKBACK_MONTHS = 12


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _trade(value: Any) -> str:
    return _required_text(value, "trade").casefold().replace("-", "_").replace(" ", "_")


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
    index = value.year * 12 + value.month - 1 - months
    year, zero_month = divmod(index, 12)
    month = zero_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _rounded_average_cents(total: int, count: int) -> int | None:
    if count == 0:
        return None
    return int(
        (Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


class VendorStore:
    """Own the vendor registry and read recorded work-order observations."""

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
        """Open a transaction and initialize only ``pm_vendors``."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS pm_vendors (
                name TEXT NOT NULL,
                trade TEXT NOT NULL,
                coi_expires TEXT,
                rate_notes TEXT,
                PRIMARY KEY(name, trade)
            );
            CREATE INDEX IF NOT EXISTS idx_pm_vendors_trade
                ON pm_vendors(trade, name);
            """
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_vendor(
        self,
        name: str,
        trade: str,
        coi_expires: date | datetime | str | None = None,
        rate_notes: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update a vendor identified by its recorded name and trade."""

        normalized_name = _required_text(name, "name")
        normalized_trade = _trade(trade)
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO pm_vendors(name, trade, coi_expires, rate_notes)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name, trade) DO UPDATE SET
                    coi_expires=excluded.coi_expires,
                    rate_notes=excluded.rate_notes
                """,
                (
                    normalized_name,
                    normalized_trade,
                    _iso_date(coi_expires, "coi_expires", nullable=True),
                    _optional_text(rate_notes, "rate_notes"),
                ),
            )
            row = connection.execute(
                "SELECT * FROM pm_vendors WHERE name=? AND trade=?",
                (normalized_name, normalized_trade),
            ).fetchone()
        if row is None:
            raise RuntimeError("vendor upsert did not produce a durable row")
        result = dict(row)
        result["source_ref"] = {
            "table": "pm_vendors",
            "primary_key": {"name": normalized_name, "trade": normalized_trade},
            "database": str(self.db_path),
        }
        return result

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            is not None
        )

    def compare_vendors(
        self,
        trade: str,
        as_of: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Compare only empirical order cost and current SLA/repeat observations."""

        normalized_trade = _trade(trade)
        on_date = _as_of(as_of)
        with self.connection() as connection:
            vendor_rows = connection.execute(
                "SELECT * FROM pm_vendors WHERE trade=? ORDER BY name",
                (normalized_trade,),
            ).fetchall()
            if self._table_exists(connection, "pm_workorders"):
                order_rows = connection.execute(
                    """
                    SELECT * FROM pm_workorders
                    WHERE opened<=?
                    ORDER BY opened, workorder_id
                    """,
                    (on_date.isoformat(),),
                ).fetchall()
            else:
                order_rows = []

        registered = [dict(row) for row in vendor_rows]
        orders = [dict(row) for row in order_rows]
        all_by_asset_system: dict[tuple[str, str], list[date]] = {}
        for order in orders:
            key = (str(order["asset"]), str(order["system"]))
            all_by_asset_system.setdefault(key, []).append(date.fromisoformat(str(order["opened"])))

        comparisons: list[dict[str, Any]] = []
        without_history: list[str] = []
        for vendor in registered:
            name = str(vendor["name"])
            history = [
                order
                for order in orders
                if order.get("vendor") is not None
                and str(order["vendor"]).strip().casefold() == name.casefold()
            ]
            if not history:
                without_history.append(name)
                continue

            known_costs = [int(order["cost_cents"]) for order in history if order["cost_cents"] is not None]
            due_dated_active = [
                order
                for order in history
                if order["due"] is not None
                and str(order["status"]).casefold() not in _TERMINAL_STATUSES
            ]
            overdue = [
                order
                for order in due_dated_active
                if date.fromisoformat(str(order["due"])) < on_date
            ]
            repeated_orders = 0
            for order in history:
                opened = date.fromisoformat(str(order["opened"]))
                lower = _subtract_months(opened, _REPEAT_LOOKBACK_MONTHS)
                key = (str(order["asset"]), str(order["system"]))
                if any(lower <= prior < opened for prior in all_by_asset_system.get(key, [])):
                    repeated_orders += 1

            coi_expires = (
                date.fromisoformat(str(vendor["coi_expires"]))
                if vendor["coi_expires"] is not None
                else None
            )
            comparison = {
                "name": name,
                "trade": normalized_trade,
                "coi_expires": vendor["coi_expires"],
                "coi_status": (
                    "not_recorded"
                    if coi_expires is None
                    else "expired"
                    if coi_expires < on_date
                    else "current"
                ),
                "rate_notes": vendor["rate_notes"],
                "recorded_order_count": len(history),
                "order_count": len(history),
                "total_recorded_cost_cents": sum(known_costs),
                "average_recorded_cost_cents": _rounded_average_cents(
                    sum(known_costs), len(known_costs)
                ),
                "actual_response_days": None,
                "open_overdue_rate": (
                    round(len(overdue) / len(due_dated_active), 4)
                    if due_dated_active
                    else None
                ),
                "repeat_rate": round(repeated_orders / len(history), 4),
                "cost": {
                    "priced_order_count": len(known_costs),
                    "missing_cost_count": len(history) - len(known_costs),
                    "total_recorded_cost_cents": sum(known_costs),
                    "average_recorded_cost_cents": _rounded_average_cents(
                        sum(known_costs), len(known_costs)
                    ),
                    "average_rounding": "nearest cent, ROUND_HALF_UP",
                },
                "response": {
                    "actual_response_days": None,
                    "status": "unavailable",
                    "reason": (
                        "pm_workorders records opened/due/current status but has no response or "
                        "completion timestamp; actual response time cannot be inferred"
                    ),
                },
                "recorded_sla_exposure": {
                    "due_dated_active_order_count": len(due_dated_active),
                    "open_overdue_count": len(overdue),
                    "open_overdue_rate": (
                        round(len(overdue) / len(due_dated_active), 4)
                        if due_dated_active
                        else None
                    ),
                    "as_of": on_date.isoformat(),
                    "basis": "current non-terminal recorded orders only; not historical response time",
                },
                "repeat_observation": {
                    "repeat_order_count": repeated_orders,
                    "recorded_order_count": len(history),
                    "repeat_rate": round(repeated_orders / len(history), 4),
                    "definition": (
                        "vendor order with a prior recorded order for the same asset + system "
                        f"during the preceding {_REPEAT_LOOKBACK_MONTHS} months"
                    ),
                    "causality_warning": (
                        "repeat association does not establish vendor fault or identify root cause"
                    ),
                },
            }
            comparisons.append(comparison)

        comparisons.sort(
            key=lambda row: (
                row["cost"]["average_recorded_cost_cents"] is None,
                row["cost"]["average_recorded_cost_cents"] or 0,
                row["recorded_sla_exposure"]["open_overdue_rate"] is None,
                row["recorded_sla_exposure"]["open_overdue_rate"] or 0,
                row["repeat_observation"]["repeat_rate"],
                row["name"].casefold(),
            )
        )
        return {
            "trade": normalized_trade,
            "as_of": on_date.isoformat(),
            "status": "recorded_history" if comparisons else "no_recorded_workorder_history",
            "vendors": comparisons,
            "comparisons": comparisons,
            "registered_vendor_count": len(registered),
            "registered_vendors_without_order_history": without_history,
            "history_basis": "pm_workorders rows whose vendor matches a registered vendor name",
            "ranking_note": (
                "Ordering is descriptive, not a winner recommendation; job scope and asset mix "
                "are not normalized. Vendors without recorded orders are not scored."
            ),
            "honest_gaps": [
                "Actual response time is unavailable because no response/completion timestamp is stored.",
                "Repeat association is a screening metric and does not establish workmanship quality.",
            ],
        }


def record_vendor(
    name: str,
    trade: str,
    coi_expires: date | datetime | str | None = None,
    rate_notes: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Record a vendor through a short-lived store."""

    return VendorStore(db_path).record_vendor(name, trade, coi_expires, rate_notes)


def compare_vendors(
    trade: str,
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Compare registered vendors using recorded work-order history only."""

    return VendorStore(db_path).compare_vendors(trade, as_of)


__all__ = ["VendorStore", "compare_vendors", "record_vendor"]
