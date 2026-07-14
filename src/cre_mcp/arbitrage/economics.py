"""Economics for commercial master-lease and sublease arbitrage."""

from __future__ import annotations

import math
from typing import Any


def _nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def _rate(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)) or value <= -1:
        raise ValueError(f"{name} must be finite and greater than -1")
    return float(value)


def master_lease_arbitrage(
    *,
    master_rent_annual: float,
    building_sqft: float,
    sublease_rent_psf: float,
    sublease_occupancy: float = 0.92,
    ti_psf: float = 0.0,
    free_rent_months: float = 0.0,
    mgmt_pct: float = 0.05,
    other_annual_costs: float = 0.0,
    term_years: int = 5,
    your_rent_escalation_pct: float = 0.03,
    sublease_escalation_pct: float = 0.03,
    personal_guarantee: bool = True,
) -> dict[str, Any]:
    """Calculate annual spread and term projection without hiding vacancy risk.

    Occupancy is an underwriting assumption, not a promise. The master tenant owes
    the owner the master rent even when no subtenant is paying rent.
    """

    master_rent = _nonnegative("master_rent_annual", master_rent_annual)
    sqft = _nonnegative("building_sqft", building_sqft)
    if sqft == 0:
        raise ValueError("building_sqft must be greater than zero")
    sublease_psf = _nonnegative("sublease_rent_psf", sublease_rent_psf)
    occupancy = _nonnegative("sublease_occupancy", sublease_occupancy)
    if occupancy > 1:
        raise ValueError("sublease_occupancy must be between 0 and 1")
    tenant_improvements = _nonnegative("ti_psf", ti_psf)
    free_months = _nonnegative("free_rent_months", free_rent_months)
    management_rate = _nonnegative("mgmt_pct", mgmt_pct)
    if management_rate > 1:
        raise ValueError("mgmt_pct must be between 0 and 1")
    other_costs = _nonnegative("other_annual_costs", other_annual_costs)
    if isinstance(term_years, bool) or not isinstance(term_years, int) or term_years < 1:
        raise ValueError("term_years must be a positive integer")
    master_escalation = _rate(
        "your_rent_escalation_pct", your_rent_escalation_pct
    )
    sublease_escalation = _rate(
        "sublease_escalation_pct", sublease_escalation_pct
    )
    if not isinstance(personal_guarantee, bool):
        raise ValueError("personal_guarantee must be a boolean")

    gross_potential_sublease_income = sublease_psf * sqft
    gross_sublease_income = gross_potential_sublease_income * occupancy
    amortized_ti = (tenant_improvements * sqft) / max(term_years, 1)
    amortized_free_rent = (
        (free_months / 12) * gross_potential_sublease_income / max(term_years, 1)
    )
    variable_cost = management_rate * gross_sublease_income
    fixed_cost = master_rent + amortized_ti + amortized_free_rent + other_costs
    total_cost = fixed_cost + variable_cost
    net_cash_flow_annual = gross_sublease_income - total_cost
    margin_pct = (
        net_cash_flow_annual / gross_sublease_income
        if gross_sublease_income
        else None
    )
    rent_coverage = gross_sublease_income / master_rent if master_rent else None
    breakeven_occupancy = (
        fixed_cost / gross_potential_sublease_income
        if gross_potential_sublease_income
        else None
    )
    breakeven_sublease_psf = (
        fixed_cost / (sqft * occupancy) if sqft * occupancy else None
    )

    projection: list[dict[str, float | int | None]] = []
    full_term_master_rent = 0.0
    for year in range(1, term_years + 1):
        year_offset = year - 1
        year_income = gross_sublease_income * (
            (1 + sublease_escalation) ** year_offset
        )
        year_master_rent = master_rent * (
            (1 + master_escalation) ** year_offset
        )
        full_term_master_rent += year_master_rent
        year_cost = (
            year_master_rent
            + amortized_ti
            + amortized_free_rent
            + other_costs
            + management_rate * year_income
        )
        year_net = year_income - year_cost
        projection.append(
            {
                "year": year,
                "income": year_income,
                "cost": year_cost,
                "net": year_net,
                "margin": year_net / year_income if year_income else None,
            }
        )

    risk_flags = ["negative_carry"]
    if rent_coverage is not None and rent_coverage < 1.25:
        risk_flags.append("thin_coverage")
    if breakeven_occupancy is not None and breakeven_occupancy > 0.85:
        risk_flags.append("fragile_occupancy")
    if net_cash_flow_annual <= 0:
        risk_flags.append("non_positive_cash_flow")
    if personal_guarantee:
        risk_flags.append("personal_guarantee_amplifies_loss")

    coverage_text = (
        f"First-year modeled rent coverage is {rent_coverage:.2f}x"
        if rent_coverage is not None
        else "First-year rent coverage is unknown because annual master rent is zero"
    )
    breakeven_text = (
        f"modeled breakeven occupancy is {breakeven_occupancy:.1%}"
        if breakeven_occupancy is not None
        else "breakeven occupancy is unknown because potential sublease rent is zero"
    )
    explanation = (
        f"At the stated {occupancy:.1%} occupancy assumption, modeled first-year "
        f"sublease income is ${gross_sublease_income:,.2f} and modeled net cash "
        f"flow is ${net_cash_flow_annual:,.2f}. {coverage_text}, and {breakeven_text}. "
        f"This is not risk-free spread: you still owe ${master_rent:,.2f} of annual "
        "master rent when the sublease is vacant or the subtenant defaults. "
        "The occupancy, rent, costs, and tenant credit must be independently verified."
    )

    return {
        "master_rent_annual": master_rent,
        "building_sqft": sqft,
        "sublease_rent_psf": sublease_psf,
        "sublease_occupancy": occupancy,
        "ti_psf": tenant_improvements,
        "free_rent_months": free_months,
        "mgmt_pct": management_rate,
        "other_annual_costs": other_costs,
        "term_years": term_years,
        "your_rent_escalation_pct": master_escalation,
        "sublease_escalation_pct": sublease_escalation,
        "personal_guarantee": personal_guarantee,
        "gross_potential_sublease_income": gross_potential_sublease_income,
        "gross_sublease_income": gross_sublease_income,
        "amortized_ti": amortized_ti,
        "amortized_free_rent": amortized_free_rent,
        "variable_cost": variable_cost,
        "fixed_cost": fixed_cost,
        "total_cost": total_cost,
        "net_cash_flow_annual": net_cash_flow_annual,
        "margin_pct": margin_pct,
        "rent_coverage": rent_coverage,
        "breakeven_occupancy": breakeven_occupancy,
        "breakeven_sublease_psf": breakeven_sublease_psf,
        "negative_carry_exposure_annual": master_rent,
        "negative_carry_exposure_full_term": full_term_master_rent,
        "negative_carry_note": (
            "The master tenant owes the owner rent even if the sublease is vacant; "
            "for a single-tenant strategy, the liability continues for the whole term."
        ),
        "projection": projection,
        "risk_flags": risk_flags,
        "explanation": explanation,
    }


__all__ = ["master_lease_arbitrage"]
