"""Plain JSON-friendly boundaries for master-lease control operations.

These functions are intentionally not registered with FastMCP.  Implementation
modules raise precise exceptions; this boundary converts every failure to the
repository's stable ``{"error": ...}`` shape.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from cre_mcp.config import CreConfig

from .breach_watch import breach_report as _breach_report
from .breach_watch import record_watch_item as _record_watch_item
from .control_books import open_position as _open_position
from .control_books import position_status as _position_status
from .control_books import record_flow as _record_flow
from .exit_package import package_control_exit as _package_control_exit
from .option_pricing import price_control_option as _price_control_option
from .scenarios import control_scenarios as _control_scenarios

logger = logging.getLogger(__name__)


def _error(tool_name: str, exc: Exception) -> dict[str, str]:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    message = message or exc.__class__.__name__
    logger.error("%s error: %s", tool_name, message)
    return {"error": message}


def open_ml_position(
    property: str,
    master_rent_cents: int,
    term_months: int,
    owner_name: str | None = None,
    security_cents: int | None = None,
    reserves_cents: int | None = None,
    started_at: str | date | datetime | None = None,
    position_id: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Open the durable control books for one signed master lease."""

    try:
        return _open_position(
            property=property,
            master_rent_cents=master_rent_cents,
            term_months=term_months,
            owner_name=owner_name,
            security_cents=security_cents,
            reserves_cents=reserves_cents,
            started_at=started_at,
            position_id=position_id,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("open_ml_position", exc)


def record_ml_flow(
    position_id: str,
    period: str,
    type: str,
    cents: int,
    note: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Append one owed, paid, billed, received, expense, or reserve flow."""

    try:
        return _record_flow(
            position_id=position_id,
            period=period,
            type=type,
            cents=cents,
            note=note,
            db_path=db_path,
        )
    except Exception as exc:
        return _error("record_ml_flow", exc)


def ml_position_status(
    position_id: str,
    period: str,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Return the rent-exposure-first control-period report."""

    try:
        return _position_status(position_id, period, db_path=db_path)
    except Exception as exc:
        return _error("ml_position_status", exc)


def ml_control_scenarios(
    position: Mapping[str, Any],
    events: Sequence[str | Mapping[str, Any]],
) -> dict[str, Any]:
    """Model bounded control-event exposures and clause review checklists."""

    try:
        return _control_scenarios(position, events)
    except Exception as exc:
        return _error("ml_control_scenarios", exc)


def price_control_option(
    option: Mapping[str, Any],
    market: Mapping[str, Any],
    position_economics: Mapping[str, Any],
) -> dict[str, Any]:
    """Price a control option while exposing every timing and growth assumption."""

    try:
        return _price_control_option(option, market, position_economics)
    except Exception as exc:
        return _error("price_control_option", exc)


def record_ml_watch_item(
    position_id: str,
    item: str,
    due_or_observed: str | date | datetime | None,
    severity: str,
    status: str,
    *,
    db_path: str | Path | CreConfig | None = None,
    watch_id: str | None = None,
) -> dict[str, Any]:
    """Record an item that may pass a subtenant breach up to the owner lease."""

    try:
        return _record_watch_item(
            position_id,
            item,
            due_or_observed,
            severity,
            status,
            db_path=db_path,
            watch_id=watch_id,
        )
    except Exception as exc:
        return _error("record_ml_watch_item", exc)


def ml_breach_report(
    position_id: str,
    as_of: str | date | datetime | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Return active sandwich-risk watch items in consequence order."""

    try:
        return _breach_report(position_id, as_of=as_of, db_path=db_path)
    except Exception as exc:
        return _error("ml_breach_report", exc)


def package_control_exit(
    position: Mapping[str, Any],
    buyer_view: bool = False,
) -> dict[str, Any]:
    """Package the net control spread, transfer screen, assumptions, and risks."""

    try:
        return _package_control_exit(position, buyer_view)
    except Exception as exc:
        return _error("package_control_exit", exc)


__all__ = [
    "open_ml_position",
    "record_ml_flow",
    "ml_position_status",
    "ml_control_scenarios",
    "price_control_option",
    "record_ml_watch_item",
    "ml_breach_report",
    "package_control_exit",
]
