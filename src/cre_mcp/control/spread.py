"""Lease-creation spread modeling for vacant retail control opportunities."""

from __future__ import annotations

import math


def _finite_number(name: str, value: float, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if number < 0 or (number == 0 and not allow_zero):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return number


def model_lease_creation_spread(
    *,
    value_vacant: float,
    achievable_rent_psf: float,
    building_sqft: float,
    market_cap_rate: float,
    ti_psf: float = 25.0,
    leasing_commission_pct: float = 0.06,
    months_vacant: int = 9,
    carry_annual: float = 0.0,
    execution_risk_haircut: float = 0.15,
) -> dict[str, float | int | None | str]:
    """Model the value created by leasing a vacant building at a market rent."""

    value_vacant = _finite_number("value_vacant", value_vacant)
    achievable_rent_psf = _finite_number(
        "achievable_rent_psf", achievable_rent_psf
    )
    building_sqft = _finite_number("building_sqft", building_sqft, allow_zero=False)
    market_cap_rate = _finite_number(
        "market_cap_rate", market_cap_rate, allow_zero=False
    )
    ti_psf = _finite_number("ti_psf", ti_psf)
    leasing_commission_pct = _finite_number(
        "leasing_commission_pct", leasing_commission_pct
    )
    carry_annual = _finite_number("carry_annual", carry_annual)
    execution_risk_haircut = _finite_number(
        "execution_risk_haircut", execution_risk_haircut
    )
    if leasing_commission_pct > 1:
        raise ValueError("leasing_commission_pct must be between 0 and 1")
    if execution_risk_haircut > 1:
        raise ValueError("execution_risk_haircut must be between 0 and 1")
    if isinstance(months_vacant, bool) or months_vacant < 0:
        raise ValueError("months_vacant must be a non-negative integer")

    annual_rent = achievable_rent_psf * building_sqft
    value_leased = annual_rent / market_cap_rate
    tenant_improvements = ti_psf * building_sqft
    leasing_commission = leasing_commission_pct * annual_rent
    vacancy_carry = carry_annual * (months_vacant / 12)
    costs = tenant_improvements + leasing_commission + vacancy_carry
    gross_spread = value_leased - value_vacant - costs
    net_spread = gross_spread * (1 - execution_risk_haircut)
    return_on_control = net_spread / value_vacant if value_vacant else None

    explanation = (
        f"At ${achievable_rent_psf:,.2f}/SF on {building_sqft:,.0f} SF, the lease "
        f"produces ${annual_rent:,.0f} of annual rent and implies "
        f"${value_leased:,.0f} of leased value at a {market_cap_rate:.2%} cap rate. "
        f"After ${costs:,.0f} of TI, commission, and carry, the gross spread is "
        f"${gross_spread:,.0f}; the {execution_risk_haircut:.0%} execution haircut "
        f"leaves a net spread of ${net_spread:,.0f}."
    )
    return {
        "value_vacant": value_vacant,
        "achievable_rent_psf": achievable_rent_psf,
        "building_sqft": building_sqft,
        "market_cap_rate": market_cap_rate,
        "annual_rent": annual_rent,
        "value_leased": value_leased,
        "ti_psf": ti_psf,
        "tenant_improvements": tenant_improvements,
        "leasing_commission_pct": leasing_commission_pct,
        "leasing_commission": leasing_commission,
        "months_vacant": months_vacant,
        "carry_annual": carry_annual,
        "vacancy_carry": vacancy_carry,
        "costs": costs,
        "total_costs": costs,
        "gross_spread": gross_spread,
        "execution_risk_haircut": execution_risk_haircut,
        "net_spread": net_spread,
        "return_on_control": return_on_control,
        "explanation": explanation,
    }


__all__ = ["model_lease_creation_spread"]
