"""Safe, plain (unregistered) boundaries for property-management operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.pmops.forensics import balance_validation as _balance_validation
from cre_mcp.pmops.forensics import (
    deferred_maintenance_screen as _deferred_maintenance_screen,
)
from cre_mcp.pmops.preventive import pm_schedule as _pm_schedule
from cre_mcp.pmops.repeats import repeat_repair_analysis as _repeat_repair_analysis
from cre_mcp.pmops.turns import record_turn as _record_turn
from cre_mcp.pmops.turns import turn_board as _turn_board
from cre_mcp.pmops.vendors import compare_vendors as _compare_vendors
from cre_mcp.pmops.vendors import record_vendor as _record_vendor
from cre_mcp.pmops.workorders import record_workorder as _record_workorder
from cre_mcp.pmops.workorders import triage_queue as _triage_queue


logger = logging.getLogger(__name__)


def _error(operation: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", operation, message)
    return {"error": message}


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
    try:
        return _record_workorder(
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
            db_path=db_path,
        )
    except Exception as exc:
        return _error("record_workorder", exc)


def triage_queue(
    as_of: date | datetime | str | None = None,
    asset: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _triage_queue(as_of, asset, db_path=db_path)
    except Exception as exc:
        return _error("triage_queue", exc)


def pm_schedule(
    assets: Sequence[Mapping[str, Any]],
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    try:
        return _pm_schedule(assets, as_of)
    except Exception as exc:
        return _error("pm_schedule", exc)


def record_vendor(
    name: str,
    trade: str,
    coi_expires: date | datetime | str | None = None,
    rate_notes: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _record_vendor(
            name,
            trade,
            coi_expires,
            rate_notes,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("record_vendor", exc)


def compare_vendors(
    trade: str,
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _compare_vendors(trade, as_of, db_path=db_path)
    except Exception as exc:
        return _error("compare_vendors", exc)


def repeat_repair_analysis(
    system: str | None = None,
    window_months: int = 24,
    as_of: date | datetime | str | None = None,
    building_sf: float | None = None,
    floors: int = 1,
    extent: Any = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    try:
        return _repeat_repair_analysis(
            system,
            window_months,
            as_of,
            building_sf,
            floors,
            extent,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("repeat_repair_analysis", exc)


def record_turn(
    unit: str,
    moveout_date: date | datetime | str,
    scope_items: Sequence[Mapping[str, Any]],
    vendor: str | None = None,
    target_ready: date | datetime | str | None = None,
    status: str = "inspect",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return _record_turn(
            unit,
            moveout_date,
            scope_items,
            vendor,
            target_ready,
            status,
            db_path,
        )
    except Exception as exc:
        return _error("record_turn", exc)


def turn_board(
    as_of: date | datetime | str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        return _turn_board(as_of, db_path)
    except Exception as exc:
        return _error("turn_board", exc)


def deferred_maintenance_screen(
    expense_lines: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        return _deferred_maintenance_screen(expense_lines)
    except Exception as exc:
        return _error("deferred_maintenance_screen", exc)


def balance_validation(
    balances: Mapping[str, Any],
    expected: Mapping[str, Any] | None = None,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    # NOTE: internal BookStore injection stays off the MCP boundary — FastMCP
    # cannot schema arbitrary classes (same fix as relations tools).
    try:
        return _balance_validation(
            balances,
            expected,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("balance_validation", exc)


__all__ = [
    "balance_validation",
    "compare_vendors",
    "deferred_maintenance_screen",
    "pm_schedule",
    "record_turn",
    "record_vendor",
    "record_workorder",
    "repeat_repair_analysis",
    "triage_queue",
    "turn_board",
]
