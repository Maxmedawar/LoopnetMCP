"""Plain valuation callables for later registration by the server owner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cre_mcp.valuation.approaches import reconcile_approaches as _reconcile_approaches
from cre_mcp.valuation.incentives import incentive_cliff as _incentive_cliff
from cre_mcp.valuation.insurance_model import insurance_repricing as _insurance_repricing
from cre_mcp.valuation.interests import value_interest_split as _value_interest_split
from cre_mcp.valuation.liquidation import forced_sale_value as _forced_sale_value
from cre_mcp.valuation.residual import risk_adjusted_residual as _risk_adjusted_residual
from cre_mcp.valuation.rollover import suite_rollover_model as _suite_rollover_model


def _safe(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Keep invalid tool inputs on the repository's structured error boundary."""
    try:
        result = call()
    except (ArithmeticError, TypeError, ValueError) as exc:
        return {"error": str(exc)}
    return result if isinstance(result, dict) else {"error": "valuation result was not a dictionary"}


def suite_rollover_model(
    suites: Sequence[Mapping[str, Any]] | None,
    hold_years: float | None = 5.0,
    analysis_date: str | None = None,
    renewal_probability_conventions: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Model suite rollover; this plain function is intentionally not registered."""
    return _safe(
        lambda: _suite_rollover_model(
            suites,
            hold_years,
            analysis_date,
            renewal_probability_conventions,
        )
    )


def value_interest_split(
    property_value: Mapping[str, Any] | Sequence[float] | float | None,
    interest: str | None,
    terms: Mapping[str, Any] | None,
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Value a stated property interest without presenting an appraisal."""
    return _safe(
        lambda: _value_interest_split(property_value, interest, terms, discount_rate)
    )


def reconcile_valuation_approaches(
    income: Mapping[str, Any] | None,
    sales_comps: Sequence[Mapping[str, Any]] | None,
    cost: Mapping[str, Any] | None,
    subject_sf: float | None = None,
    weights: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile approaches by explanation, with optional caller-chosen weights."""
    return _safe(
        lambda: _reconcile_approaches(income, sales_comps, cost, subject_sf, weights)
    )


def forced_sale_value(
    market_value: Mapping[str, Any] | Sequence[float] | float | None,
    marketing_period: float | None,
    market_liquidity: str | None,
    cost_of_sale: Mapping[str, Any] | Sequence[float] | float | None,
    carrying_costs: Mapping[str, Any] | Sequence[float] | float | None = None,
) -> dict[str, Any]:
    """Estimate a forced-sale range from explicitly cited conventions."""
    return _safe(
        lambda: _forced_sale_value(
            market_value,
            marketing_period,
            market_liquidity,
            cost_of_sale,
            carrying_costs,
        )
    )


def incentive_cliff_analysis(
    incentives: Sequence[Mapping[str, Any]] | None,
    noi: Mapping[str, Any] | Sequence[float] | float | None,
) -> dict[str, Any]:
    """Return incentive-expiration and clawback exposure timelines."""
    return _safe(lambda: _incentive_cliff(incentives, noi))


def risk_adjusted_residual(
    program: Mapping[str, Any] | None,
    probabilities: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return convention-weighted residual values, not development predictions."""
    return _safe(lambda: _risk_adjusted_residual(program, probabilities))


def insurance_repricing_impact(
    current: Mapping[str, Any] | None,
    quotes: Sequence[Mapping[str, Any]] | None,
    noi: Mapping[str, Any] | Sequence[float] | float | None,
) -> dict[str, Any]:
    """Bridge quoted premiums to NOI and flag stated coverage gaps."""
    return _safe(lambda: _insurance_repricing(current, quotes, noi))


__all__ = [
    "forced_sale_value",
    "incentive_cliff_analysis",
    "insurance_repricing_impact",
    "reconcile_valuation_approaches",
    "risk_adjusted_residual",
    "suite_rollover_model",
    "value_interest_split",
]
