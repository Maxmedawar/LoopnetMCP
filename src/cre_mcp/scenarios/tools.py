"""Plain scenario functions suitable for later FastMCP registration by the director."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.scenarios.breakeven import analyze_breakevens
from cre_mcp.scenarios.engine import stress_test
from cre_mcp.scenarios.leaseup import model_lease_up as _model_lease_up
from cre_mcp.scenarios.sensitivity import tornado


def stress_test_deal(
    deal_inputs: dict[str, Any],
    shocks: Mapping[str, Any] | Sequence[str] | str | None = None,
) -> dict[str, Any]:
    """Return explicitly labeled scenario calculations; this is not registered."""
    return stress_test(deal_inputs, shocks)


def sensitivity_drivers(
    deal_inputs: dict[str, Any], spans: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a labeled one-at-a-time tornado ranking; this is not registered."""
    return tornado(deal_inputs, spans)


def breakeven_analysis(
    deal_inputs: dict[str, Any], target_dscr: float | None = None
) -> dict[str, Any]:
    """Return explicit break-even thresholds; this is not registered."""
    return analyze_breakevens(deal_inputs, target_dscr)


def model_lease_up(
    suites: Sequence[Mapping[str, Any]] | None,
    leasing_velocity: float | Mapping[str, Any] | None,
    downtime_months: float | None,
    ti_per_sf: float | None,
    lc_per_sf: float | None,
    free_rent_months: float | None,
    carry_costs: float | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return an explicitly labeled monthly lease-up curve; this is not registered."""
    return _model_lease_up(
        suites,
        leasing_velocity,
        downtime_months,
        ti_per_sf,
        lc_per_sf,
        free_rent_months,
        carry_costs,
    )
