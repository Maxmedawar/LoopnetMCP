"""Safe, plain (unregistered) boundaries for construction-control functions."""

from __future__ import annotations

import logging
from typing import Any

from cre_mcp.construction.bids import level_bids as _level_bids
from cre_mcp.construction.budget import development_budget as _development_budget
from cre_mcp.construction.closeout import closeout_register as _closeout_register
from cre_mcp.construction.draws import audit_pay_app as _audit_pay_app
from cre_mcp.construction.draws import forecast_draws as _forecast_draws
from cre_mcp.construction.gmp import reconcile_gmp as _reconcile_gmp
from cre_mcp.construction.proposals import compare_proposals as _compare_proposals
from cre_mcp.construction.tracking import critical_path_slippage as _critical_path_slippage
from cre_mcp.construction.tracking import record_item as _record_item
from cre_mcp.construction.tracking import record_tracking_item as _record_tracking_item
from cre_mcp.construction.tracking import track_items as _track_items
from cre_mcp.construction.ve_percent import percent_complete as _percent_complete
from cre_mcp.construction.ve_percent import ve_option as _ve_option


logger = logging.getLogger(__name__)


def _error(operation: str, exc: Exception) -> dict[str, str]:
    logger.error("%s error: %s", operation, exc)
    return {"error": str(exc)}


def development_budget(
    program: dict[str, Any],
    local_factor: float | dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _development_budget(program, local_factor)
    except Exception as exc:
        return _error("development_budget", exc)


def compare_proposals(
    proposals: list[dict[str, Any]],
    required_scope: list[str | dict[str, Any]],
) -> dict[str, Any]:
    try:
        return _compare_proposals(proposals, required_scope)
    except Exception as exc:
        return _error("compare_proposals", exc)


def level_bids(
    bids: list[dict[str, Any]],
    scope_baseline: list[str | dict[str, Any]],
) -> dict[str, Any]:
    try:
        return _level_bids(bids, scope_baseline)
    except Exception as exc:
        return _error("level_bids", exc)


def reconcile_gmp(
    gmp: dict[str, Any],
    drawings_scope: list[str | dict[str, Any]],
) -> dict[str, Any]:
    try:
        return _reconcile_gmp(gmp, drawings_scope)
    except Exception as exc:
        return _error("reconcile_gmp", exc)


def forecast_draws(
    budget: int | dict[str, Any],
    schedule: dict[str, Any],
    loan_terms: dict[str, Any] | None = None,
    project_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _forecast_draws(budget, schedule, loan_terms, project_id, db_path)
    except Exception as exc:
        return _error("forecast_draws", exc)


def audit_pay_app(
    pay_app: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _audit_pay_app(pay_app, evidence)
    except Exception as exc:
        return _error("audit_pay_app", exc)


def record_tracking_item(
    item: dict[str, Any],
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _record_tracking_item(item, db_path)
    except Exception as exc:
        return _error("record_tracking_item", exc)


def record_item(
    project: str,
    item_type: str,
    ref: str,
    opened: str,
    due: str,
    status: str,
    critical: bool,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _record_item(
            project, item_type, ref, opened, due, status, critical, db_path
        )
    except Exception as exc:
        return _error("record_item", exc)


def track_items(
    project: str,
    item_type: str | None = None,
    status: str | None = None,
    critical: bool | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _track_items(project, item_type, status, critical, db_path)
    except Exception as exc:
        return _error("track_items", exc)


def critical_path_slippage(
    project: str,
    as_of: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    try:
        return _critical_path_slippage(project, as_of, db_path)
    except Exception as exc:
        return _error("critical_path_slippage", exc)


def ve_option(
    option: dict[str, Any],
    exit_cap: float | str | None = None,
) -> dict[str, Any]:
    try:
        return _ve_option(option, exit_cap)
    except Exception as exc:
        return _error("ve_option", exc)


def percent_complete(evidence: dict[str, Any]) -> dict[str, Any]:
    try:
        return _percent_complete(evidence)
    except Exception as exc:
        return _error("percent_complete", exc)


def closeout_register(items: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return _closeout_register(items)
    except Exception as exc:
        return _error("closeout_register", exc)


__all__ = [
    "audit_pay_app",
    "closeout_register",
    "compare_proposals",
    "critical_path_slippage",
    "development_budget",
    "forecast_draws",
    "level_bids",
    "percent_complete",
    "reconcile_gmp",
    "record_item",
    "record_tracking_item",
    "track_items",
    "ve_option",
]
