"""DSCR- and LTV-constrained deterministic debt sizing."""

from __future__ import annotations

import math
from typing import Literal

from cre_mcp.execution.guardrails import financing_guardrail
from cre_mcp.models.deals import DealContext
from cre_mcp.models.execution import DebtSizing
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.underwriting.metrics import mortgage_constant

DebtScenario = Literal["agency", "bridge", "bank"]


def _positive(value: float | int | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _fraction(value: float, name: str) -> float:
    normalized = value / 100 if value > 1 else value
    if not 0 < normalized <= 1:
        raise ValueError(f"{name} must be a decimal or percentage between 0 and 100")
    return normalized


def _rate_decimal(value: float) -> float:
    normalized = value / 100 if value > 1 else value
    if not 0 < normalized < 1:
        raise ValueError("rate must be a positive decimal or percentage below 100")
    return normalized


def anchored_rate(
    ctx: DealContext,
    anchor: str,
    spread_bps: float,
) -> tuple[float, str]:
    """Return a percent rate anchored to the covered FRED metric or fallback."""
    metric = getattr(ctx.market, anchor, None) if ctx.market is not None else None
    observed = _positive(metric.value) if metric is not None else None
    if observed is not None:
        source = f"{metric.source} ({anchor}) + {spread_bps:.0f} bps typical spread"
        return observed + spread_bps / 100, source
    fallback = T.FINANCING_FALLBACK_RATE_PCT[anchor]
    return (
        fallback + spread_bps / 100,
        f"fallback {anchor} {fallback:.2f}% + {spread_bps:.0f} bps typical spread",
    )


def _value_basis(ctx: DealContext) -> tuple[float, float, str]:
    ask = _positive(ctx.listing.price_usd)
    estimate = None
    if ctx.value_estimate is not None:
        estimate = _positive(ctx.value_estimate.mid or ctx.value_estimate.value)
    if ask is None and estimate is None:
        raise ValueError("A positive purchase price or value estimate is required")
    purchase_price = ask or estimate
    assert purchase_price is not None
    if ask is not None and estimate is not None:
        return min(ask, estimate), purchase_price, (
            "lower of asking price and the available value estimate"
        )
    if estimate is not None:
        return estimate, purchase_price, "available value estimate"
    return purchase_price, purchase_price, "asking price fallback"


def _noi(ctx: DealContext) -> float | None:
    if ctx.underwriting is not None:
        value = _positive(ctx.underwriting.noi)
        if value is not None:
            return value
    return _positive(ctx.listing.noi_usd)


def size_debt(
    ctx: DealContext,
    scenario: DebtScenario = "agency",
    *,
    ltv: float | None = None,
    rate: float | None = None,
    amort_years: int | None = None,
    min_dscr: float | None = None,
) -> DebtSizing:
    """Size proceeds at the lesser of the LTV and DSCR constraints."""
    if scenario not in T.FINANCING_DEBT_SCENARIOS:
        raise ValueError("scenario must be one of: agency, bridge, bank")
    defaults = T.FINANCING_DEBT_SCENARIOS[scenario]
    selected_ltv = _fraction(
        float(defaults["ltv"] if ltv is None else ltv),
        "ltv",
    )
    selected_amort = int(defaults["amort_years"] if amort_years is None else amort_years)
    if selected_amort <= 0:
        raise ValueError("amort_years must be greater than zero")
    selected_dscr = float(defaults["min_dscr"] if min_dscr is None else min_dscr)
    if not math.isfinite(selected_dscr) or selected_dscr <= 0:
        raise ValueError("min_dscr must be greater than zero")

    if rate is None:
        rate_pct, rate_source = anchored_rate(
            ctx,
            str(defaults["rate_anchor"]),
            float(defaults["spread_bps"]),
        )
        selected_rate = rate_pct / 100
    else:
        selected_rate = _rate_decimal(rate)
        rate_pct = selected_rate * 100
        rate_source = "caller override"

    interest_only = bool(defaults["interest_only"])
    debt_constant = (
        selected_rate
        if interest_only
        else mortgage_constant(selected_rate, selected_amort)
    )
    if debt_constant is None or debt_constant <= 0:
        raise ValueError("The selected rate and amortization cannot produce debt service")

    property_value, purchase_price, value_source = _value_basis(ctx)
    noi = _noi(ctx)
    ltv_constraint = property_value * selected_ltv
    dscr_constraint = (
        noi / (selected_dscr * debt_constant)
        if noi is not None
        else None
    )
    if dscr_constraint is not None and dscr_constraint < ltv_constraint:
        maximum_loan = dscr_constraint
        binding: Literal["ltv", "dscr"] = "dscr"
    else:
        maximum_loan = ltv_constraint
        binding = "ltv"

    annual_debt_service = maximum_loan * debt_constant
    resulting_dscr = (
        noi / annual_debt_service
        if noi is not None and annual_debt_service > 0
        else None
    )
    equity_required = max(purchase_price - maximum_loan, 0.0)
    cash_on_cash = (
        100 * (noi - annual_debt_service) / equity_required
        if noi is not None and equity_required > 0
        else None
    )
    assumptions = {
        "ltv": {"value": selected_ltv, "source": "override" if ltv is not None else scenario},
        "rate_pct": {"value": rate_pct, "source": rate_source},
        "amort_years": {
            "value": selected_amort,
            "source": "override" if amort_years is not None else scenario,
        },
        "interest_only": {"value": interest_only, "source": scenario},
        "min_dscr": {
            "value": selected_dscr,
            "source": "override" if min_dscr is not None else scenario,
        },
        "property_value": {"value": property_value, "source": value_source},
    }
    if noi is None:
        assumptions["noi_gap"] = {
            "value": None,
            "source": "NOI unavailable; proceeds are LTV-only and DSCR is untested",
        }
    return DebtSizing(
        deal_ref=f"{ctx.listing.source}:{ctx.listing.source_id}",
        scenario=scenario,
        property_value=property_value,
        purchase_price=purchase_price,
        noi=noi,
        max_loan=maximum_loan,
        proceeds=maximum_loan,
        ltv_constraint=ltv_constraint,
        dscr_constraint=dscr_constraint,
        binding_constraint=binding,
        equity_required=equity_required,
        annual_debt_service=annual_debt_service,
        dscr=resulting_dscr,
        cash_on_cash=cash_on_cash,
        assumptions_used=assumptions,
        guardrail=financing_guardrail(
            "Ask a lender to validate underwritten NOI, appraisal value, rate, debt "
            "constant, reserves, fees, recourse, and actual proceeds."
        ),
    )


__all__ = ["DebtScenario", "anchored_rate", "size_debt"]
