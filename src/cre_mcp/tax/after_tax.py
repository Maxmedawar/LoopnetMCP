"""After-tax CRE return scenarios with transparent depreciation and exit taxes."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from cre_mcp.models.deals import DealContext
from cre_mcp.models.tax import AfterTaxResult, DepreciationYear
from cre_mcp.underwriting.assumptions import UnderwritingAssumptions
from cre_mcp.underwriting.metrics import (
    annual_debt_service,
    equity_multiple,
    levered_irr,
)

RESIDENTIAL_RECOVERY_YEARS = 27.5
COMMERCIAL_RECOVERY_YEARS = 39.0
UNRECAPTURED_1250_RATE = 0.25
DEFAULT_LAND_PCT = 0.20
DEFAULT_CAPITAL_GAINS_RATE = 0.20
DEFAULT_ANNUAL_APPRECIATION = 0.02
DEFAULT_SELLING_COST_PCT = 0.06
DEFAULT_COST_SEG_ALLOCATIONS = {5: 0.10, 7: 0.05, 15: 0.15}

CPA_GATE = (
    "HARD GATE — Confirm depreciable basis, land allocation, placed-in-service date, "
    "MACRS conventions, passive-loss limits, bonus eligibility, §1245/§1250 recapture, "
    "capital gains, NIIT, and filing treatment with a CPA. Cost segregation requires a "
    "qualified study; this scenario is not a tax return or tax advice."
)


def _number(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _fraction(value: Any, label: str, *, below_one: bool = False) -> float:
    number = _number(value, label)
    normalized = number / 100 if number > 1 else number
    maximum_ok = normalized < 1 if below_one else normalized <= 1
    if normalized < 0 or not maximum_ok:
        ceiling = "below 100" if below_one else "at most 100"
        raise ValueError(f"{label} must be a decimal or percentage from 0 to {ceiling}")
    return normalized


def _positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _underwriting_value(ctx: DealContext, key: str, fallback: Any) -> Any:
    if ctx.underwriting is None:
        return fallback
    item = ctx.underwriting.assumptions_used.get(key)
    if not isinstance(item, Mapping):
        return fallback
    return item.get("value", fallback)


def _is_residential(ctx: DealContext) -> bool:
    text = " ".join(
        str(value or "").casefold()
        for value in (ctx.listing.property_type, ctx.listing.property_subtype)
    )
    return any(
        term in text
        for term in (
            "multifamily",
            "multi-family",
            "apartment",
            "residential",
            "student housing",
        )
    )


def _land_pct(ctx: DealContext, assumptions: Mapping[str, Any]) -> tuple[float, str]:
    if assumptions.get("land_pct") is not None:
        return _fraction(assumptions["land_pct"], "land_pct", below_one=True), "override"
    if (
        ctx.parcel is not None
        and _positive(ctx.parcel.land_value) is not None
        and _positive(ctx.parcel.assessed_value) is not None
    ):
        ratio = float(ctx.parcel.land_value) / float(ctx.parcel.assessed_value)
        if 0 < ratio < 1:
            return ratio, "parcel land value / assessed value"
    return DEFAULT_LAND_PCT, "conservative default; obtain assessor allocation/appraisal"


def _loan_schedule(
    loan: float,
    annual_rate: float,
    amortization_years: int,
    hold_years: int,
) -> tuple[list[float], list[float], float]:
    if loan <= 0:
        return [0.0] * hold_years, [0.0] * hold_years, 0.0
    periods = amortization_years * 12
    months = min(hold_years * 12, periods)
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        payment = loan / periods
    else:
        payment = loan * monthly_rate / (1 - (1 + monthly_rate) ** -periods)
    balance = loan
    annual_interest: list[float] = []
    annual_payments: list[float] = []
    interest_for_year = 0.0
    payments_for_year = 0.0
    for month in range(1, months + 1):
        interest = balance * monthly_rate
        principal = min(max(payment - interest, 0.0), balance)
        actual_payment = interest + principal
        balance = max(balance - principal, 0.0)
        interest_for_year += interest
        payments_for_year += actual_payment
        if month % 12 == 0:
            annual_interest.append(interest_for_year)
            annual_payments.append(payments_for_year)
            interest_for_year = 0.0
            payments_for_year = 0.0
    while len(annual_interest) < hold_years:
        annual_interest.append(0.0)
        annual_payments.append(0.0)
    return annual_interest, annual_payments, balance


def _cost_seg_allocations(assumptions: Mapping[str, Any]) -> dict[int, float]:
    raw = assumptions.get("cost_seg_allocations", DEFAULT_COST_SEG_ALLOCATIONS)
    if not isinstance(raw, Mapping):
        raise ValueError("cost_seg_allocations must be a mapping of 5/7/15-year percentages")
    parsed: dict[int, float] = {}
    for key, value in raw.items():
        try:
            life = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("cost-seg recovery classes must be 5, 7, or 15") from exc
        if life not in {5, 7, 15}:
            raise ValueError("cost-seg recovery classes must be 5, 7, or 15")
        parsed[life] = _fraction(value, f"cost-seg {life}-year allocation")
    if sum(parsed.values()) >= 1:
        raise ValueError("cost-seg allocations must total less than 100% of improvement basis")
    return parsed


def _depreciation_schedule(
    improvement_basis: float,
    recovery_period: float,
    hold_years: int,
    marginal_rate: float,
    annual_taxable_before_depreciation: list[float],
    *,
    cost_seg: bool,
    bonus_pct: float,
    allocations: dict[int, float],
    passive_losses_usable: bool,
) -> tuple[list[DepreciationYear], float, float]:
    eligible_basis = improvement_basis * sum(allocations.values()) if cost_seg else 0.0
    building_basis = improvement_basis - eligible_basis
    bonus = eligible_basis * bonus_pct
    class_bases = {
        life: improvement_basis * pct * (1 - bonus_pct)
        for life, pct in allocations.items()
    } if cost_seg else {}
    building_annual = building_basis / recovery_period
    schedule: list[DepreciationYear] = []
    cumulative_building = 0.0
    cumulative_cost_seg = 0.0
    for year in range(1, hold_years + 1):
        building_dep = min(
            building_annual,
            max(building_basis - cumulative_building, 0.0),
        )
        regular_cost_seg = sum(
            basis / life
            for life, basis in class_bases.items()
            if year <= life
        )
        bonus_for_year = bonus if year == 1 else 0.0
        cost_seg_dep = regular_cost_seg + bonus_for_year
        cumulative_building += building_dep
        cumulative_cost_seg += cost_seg_dep
        total = building_dep + cost_seg_dep
        potential_shield = total * marginal_rate
        taxable_before = annual_taxable_before_depreciation[year - 1]
        tax_without_depreciation = max(taxable_before, 0.0) * marginal_rate
        taxable_after = taxable_before - total
        if passive_losses_usable:
            tax_after = taxable_after * marginal_rate
        else:
            tax_after = max(taxable_after, 0.0) * marginal_rate
        usable_shield = tax_without_depreciation - tax_after
        schedule.append(
            DepreciationYear(
                year=year,
                building_depreciation=round(building_dep, 2),
                cost_seg_depreciation=round(regular_cost_seg, 2),
                bonus_depreciation=round(bonus_for_year, 2),
                total_depreciation=round(total, 2),
                potential_tax_shield=round(potential_shield, 2),
                modeled_usable_tax_shield=round(usable_shield, 2),
            )
        )
    return schedule, cumulative_building, cumulative_cost_seg


def after_tax_returns(
    ctx: DealContext,
    assumptions: Mapping[str, Any] | None = None,
) -> AfterTaxResult:
    """Compare pre-tax and after-tax returns under explicit, CPA-gated assumptions."""
    values = dict(assumptions or {})
    price = _positive(values.get("purchase_price")) or _positive(ctx.listing.price_usd)
    if price is None:
        raise ValueError("A positive purchase price is required for after-tax returns")
    hold_years = int(values.get("hold_years", 5))
    if hold_years <= 0 or hold_years > 50:
        raise ValueError("hold_years must be between 1 and 50")
    marginal_rate = _fraction(values.get("marginal_rate", 0.37), "marginal_rate")
    capital_gains_rate = _fraction(
        values.get("capital_gains_rate", DEFAULT_CAPITAL_GAINS_RATE),
        "capital_gains_rate",
    )
    bonus_value = values.get("bonus_pct")
    bonus_pct = 0.0 if bonus_value is None else _fraction(bonus_value, "bonus_pct")
    cost_seg = bool(values.get("cost_seg", False))
    if bonus_pct > 0 and not cost_seg:
        raise ValueError("bonus_pct requires cost_seg=True and a qualified cost-segregation study")
    passive_losses_usable = bool(values.get("passive_losses_usable", False))
    land_pct, land_source = _land_pct(ctx, values)
    land_basis = price * land_pct
    improvement_basis = price - land_basis
    recovery_period = (
        RESIDENTIAL_RECOVERY_YEARS if _is_residential(ctx) else COMMERCIAL_RECOVERY_YEARS
    )
    allocations = _cost_seg_allocations(values) if cost_seg else {}

    property_defaults = UnderwritingAssumptions.for_property_type(ctx.listing.property_type)
    ltv = _fraction(
        values.get("ltv", _underwriting_value(ctx, "ltv", property_defaults.ltv)),
        "ltv",
        below_one=True,
    )
    annual_rate = _fraction(
        values.get(
            "annual_interest_rate",
            _underwriting_value(
                ctx,
                "annual_interest_rate",
                property_defaults.annual_interest_rate,
            ),
        ),
        "annual_interest_rate",
    )
    amortization_years = int(
        values.get(
            "amortization_years",
            _underwriting_value(
                ctx,
                "amortization_years",
                property_defaults.amortization_years,
            ),
        )
    )
    if amortization_years <= 0:
        raise ValueError("amortization_years must be greater than zero")
    initial_debt = price * ltv
    equity_invested = price - initial_debt
    annual_interest, annual_payments, debt_balance = _loan_schedule(
        initial_debt,
        annual_rate,
        amortization_years,
        hold_years,
    )
    modeled_debt_service = annual_debt_service(
        initial_debt,
        annual_rate,
        amortization_years,
    ) or 0.0
    noi = _positive(values.get("noi"))
    if noi is None and ctx.underwriting is not None:
        noi = _positive(ctx.underwriting.noi)
    noi = noi or _positive(ctx.listing.noi_usd)
    if noi is None:
        raise ValueError("A positive NOI is required for after-tax returns")
    noi_growth = _fraction(values.get("annual_noi_growth_rate", 0.0), "annual_noi_growth_rate")
    annual_noi = [noi * ((1 + noi_growth) ** (year - 1)) for year in range(1, hold_years + 1)]
    annual_pre_tax = [
        annual_noi[index] - annual_payments[index]
        for index in range(hold_years)
    ]
    annual_taxable_before_dep = [
        annual_noi[index] - annual_interest[index]
        for index in range(hold_years)
    ]
    depreciation, building_dep, cost_seg_dep = _depreciation_schedule(
        improvement_basis,
        recovery_period,
        hold_years,
        marginal_rate,
        annual_taxable_before_dep,
        cost_seg=cost_seg,
        bonus_pct=bonus_pct,
        allocations=allocations,
        passive_losses_usable=passive_losses_usable,
    )
    appreciation = _fraction(
        values.get("annual_appreciation_rate", DEFAULT_ANNUAL_APPRECIATION),
        "annual_appreciation_rate",
    )
    exit_price = _positive(values.get("exit_sale_price")) or price * ((1 + appreciation) ** hold_years)
    selling_cost_pct = _fraction(
        values.get("selling_cost_pct", DEFAULT_SELLING_COST_PCT),
        "selling_cost_pct",
        below_one=True,
    )
    net_sale_price = exit_price * (1 - selling_cost_pct)
    total_depreciation = min(building_dep + cost_seg_dep, improvement_basis)
    adjusted_basis = price - total_depreciation
    total_gain = max(net_sale_price - adjusted_basis, 0.0)
    unrecaptured_1250_gain = min(building_dep, total_gain)
    remaining_gain = max(total_gain - unrecaptured_1250_gain, 0.0)
    section_1245_recapture = min(cost_seg_dep, remaining_gain)
    remaining_capital_gain = max(remaining_gain - section_1245_recapture, 0.0)
    unrecaptured_1250_tax = unrecaptured_1250_gain * UNRECAPTURED_1250_RATE
    section_1245_tax = section_1245_recapture * marginal_rate
    capital_gains_tax = remaining_capital_gain * capital_gains_rate
    total_exit_tax = unrecaptured_1250_tax + section_1245_tax + capital_gains_tax

    pre_tax_flows = [-equity_invested, *annual_pre_tax]
    pre_tax_sale_proceeds = max(net_sale_price - debt_balance, 0.0)
    pre_tax_flows[-1] += pre_tax_sale_proceeds
    after_tax_annual: list[float] = []
    for index, cash in enumerate(annual_pre_tax):
        taxable = annual_taxable_before_dep[index] - depreciation[index].total_depreciation
        if passive_losses_usable:
            current_tax = taxable * marginal_rate
        else:
            current_tax = max(taxable, 0.0) * marginal_rate
        after_tax_annual.append(cash - current_tax)
    after_tax_flows = [-equity_invested, *after_tax_annual]
    after_tax_flows[-1] += max(pre_tax_sale_proceeds - total_exit_tax, 0.0)
    pre_tax_irr = levered_irr(pre_tax_flows)
    after_tax_irr = levered_irr(after_tax_flows)
    pre_tax_multiple = equity_multiple(sum(pre_tax_flows[1:]), equity_invested)
    after_tax_multiple = equity_multiple(sum(after_tax_flows[1:]), equity_invested)

    return AfterTaxResult(
        deal_ref=f"{ctx.listing.source}:{ctx.listing.source_id}",
        purchase_price=round(price, 2),
        equity_invested=round(equity_invested, 2),
        initial_debt=round(initial_debt, 2),
        improvement_basis=round(improvement_basis, 2),
        land_basis=round(land_basis, 2),
        recovery_period_years=recovery_period,
        depreciation_schedule=depreciation,
        total_building_depreciation=round(building_dep, 2),
        total_cost_seg_depreciation=round(cost_seg_dep, 2),
        total_depreciation=round(total_depreciation, 2),
        adjusted_tax_basis_at_exit=round(adjusted_basis, 2),
        exit_sale_price=round(exit_price, 2),
        net_sale_price_before_debt=round(net_sale_price, 2),
        debt_balance_at_exit=round(debt_balance, 2),
        total_gain=round(total_gain, 2),
        unrecaptured_1250_gain=round(unrecaptured_1250_gain, 2),
        unrecaptured_1250_rate=UNRECAPTURED_1250_RATE,
        unrecaptured_1250_tax=round(unrecaptured_1250_tax, 2),
        section_1245_recapture=round(section_1245_recapture, 2),
        section_1245_recapture_tax=round(section_1245_tax, 2),
        remaining_capital_gain=round(remaining_capital_gain, 2),
        capital_gains_tax=round(capital_gains_tax, 2),
        total_exit_tax=round(total_exit_tax, 2),
        pre_tax_cash_flows=[round(item, 2) for item in pre_tax_flows],
        after_tax_cash_flows=[round(item, 2) for item in after_tax_flows],
        pre_tax_irr_pct=round(pre_tax_irr, 6) if pre_tax_irr is not None else None,
        after_tax_irr_pct=round(after_tax_irr, 6) if after_tax_irr is not None else None,
        pre_tax_equity_multiple=round(pre_tax_multiple, 6) if pre_tax_multiple is not None else None,
        after_tax_equity_multiple=round(after_tax_multiple, 6) if after_tax_multiple is not None else None,
        assumptions_used={
            "marginal_rate": marginal_rate,
            "capital_gains_rate": capital_gains_rate,
            "unrecaptured_1250_rate": UNRECAPTURED_1250_RATE,
            "land_pct": {"value": land_pct, "source": land_source},
            "recovery_period_years": recovery_period,
            "cost_seg": cost_seg,
            "cost_seg_allocations": allocations,
            "cost_seg_method": "simplified straight-line over 5/7/15-year classes; actual MACRS conventions require the study/CPA",
            "bonus_pct": bonus_pct,
            "bonus_note": "No bonus assumed when omitted; eligibility and elected percentage are placed-in-service/fact specific.",
            "passive_losses_usable": passive_losses_usable,
            "hold_years": hold_years,
            "ltv": ltv,
            "annual_interest_rate": annual_rate,
            "amortization_years": amortization_years,
            "annual_debt_service_year_one": modeled_debt_service,
            "noi_year_one": noi,
            "annual_noi_growth_rate": noi_growth,
            "annual_appreciation_rate": appreciation,
            "selling_cost_pct": selling_cost_pct,
            "mid_month_convention": "not modeled; full-year educational scenario only",
            "tax_scope_gaps": "state/local tax, NIIT, passive loss carryforwards, entity allocations, transaction costs, and special limitations are excluded",
        },
        cpa_gate=CPA_GATE,
    )


__all__ = [
    "COMMERCIAL_RECOVERY_YEARS",
    "CPA_GATE",
    "DEFAULT_COST_SEG_ALLOCATIONS",
    "RESIDENTIAL_RECOVERY_YEARS",
    "UNRECAPTURED_1250_RATE",
    "after_tax_returns",
]
