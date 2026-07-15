"""Safe, unregistered function boundaries for physical diligence.

These functions intentionally are not decorated or added to the FastMCP
registry.  The integration owner can register them later.  Each boundary
returns ``{"error": ...}`` instead of leaking validation/runtime exceptions.
"""

from __future__ import annotations

import logging
from typing import Any

from cre_mcp.physical.capex import findings_to_capex as _findings_to_capex
from cre_mcp.physical.code_exposure import ada_code_exposure as _ada_code_exposure
from cre_mcp.physical.register import physical_risk_register as _physical_risk_register
from cre_mcp.physical.rul import remaining_useful_life as _remaining_useful_life
from cre_mcp.physical.vintage import vintage_risk_screen as _vintage_risk_screen


logger = logging.getLogger(__name__)


def _error(operation: str, exc: Exception) -> dict[str, str]:
    logger.error("%s error: %s", operation, exc)
    return {"error": str(exc)}


def estimate_capex_from_findings(
    findings: list[dict[str, Any]],
    building: dict[str, Any],
) -> dict[str, Any]:
    """Convert structured inspection findings to convention-based CapEx ranges."""

    try:
        return _findings_to_capex(findings, building)
    except Exception as exc:
        return _error("estimate_capex_from_findings", exc)


def remaining_useful_life(
    system: str,
    install_year_or_age: int | float | dict[str, Any],
    condition: str,
    maintenance_quality: str | None = None,
) -> dict[str, Any]:
    """Return a safe RUL convention estimate."""

    try:
        return _remaining_useful_life(
            system,
            install_year_or_age,
            condition,
            maintenance_quality,
        )
    except Exception as exc:
        return _error("remaining_useful_life", exc)


def vintage_risk_screen(
    year_built: int,
    building_type: str,
    state: str | None = None,
) -> dict[str, Any]:
    """Return a safe construction-era risk screen."""

    try:
        return _vintage_risk_screen(year_built, building_type, state)
    except Exception as exc:
        return _error("vintage_risk_screen", exc)


def ada_code_exposure(
    building: dict[str, Any],
    planned: dict[str, Any],
) -> dict[str, Any]:
    """Return a safe accessibility/code-trigger screen."""

    try:
        return _ada_code_exposure(building, planned)
    except Exception as exc:
        return _error("ada_code_exposure", exc)


def physical_risk_register(
    entries: list[dict[str, Any]] | dict[str, Any],
    deal_id: str | None = None,
) -> dict[str, Any]:
    """Return a safe, ranked physical-risk register."""

    try:
        return _physical_risk_register(entries, deal_id=deal_id)
    except Exception as exc:
        return _error("physical_risk_register", exc)


__all__ = [
    "ada_code_exposure",
    "estimate_capex_from_findings",
    "physical_risk_register",
    "remaining_useful_life",
    "vintage_risk_screen",
]
