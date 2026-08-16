"""Pure standard commercial-real-estate underwriting metrics."""

import math
from collections.abc import Iterable, Sequence
from typing import Any

from cre_mcp.models.listings import Listing
from cre_mcp.models.underwriting import UnderwritingResult
from cre_mcp.underwriting.assumptions import UnderwritingAssumptions

TENANT_CREDIT_TABLE = {
    "mcdonald's": "BBB+",
    "mcdonalds": "BBB+",
    "starbucks": "BBB+",
    "walgreens": "BBB-",
    "cvs": "BBB",
    "cvs pharmacy": "BBB",
    "dollar general": "BBB",
    "walmart": "AA",
    "target": "A",
    "chick-fil-a": "A",
    "7-eleven": "A",
    "home depot": "A",
    "lowe's": "BBB+",
    "lowes": "BBB+",
}


def _valid(*values: float | int | None) -> bool:
    return all(value is not None and math.isfinite(float(value)) for value in values)


def net_operating_income(
    gross_potential_rent: float | None,
    vacancy_rate: float | None,
    other_income: float | None,
    operating_expenses: float | None,
) -> float | None:
    """Return EGI minus operating expenses."""
    if not _valid(gross_potential_rent, vacancy_rate, other_income, operating_expenses):
        return None
    assert gross_potential_rent is not None
    assert vacancy_rate is not None
    assert other_income is not None
    assert operating_expenses is not None
    if gross_potential_rent < 0 or not 0 <= vacancy_rate <= 1:
        return None
    return gross_potential_rent * (1 - vacancy_rate) + other_income - operating_expenses


noi = net_operating_income


def cap_rate(noi_value: float | None, price: float | None) -> float | None:
    """Return NOI divided by price as a percentage."""
    if not _valid(noi_value, price) or not price:
        return None
    return 100 * float(noi_value) / float(price)


def grm(price: float | None, gross_potential_rent: float | None) -> float | None:
    """Return price divided by annual gross potential rent."""
    if not _valid(price, gross_potential_rent) or not gross_potential_rent:
        return None
    return float(price) / float(gross_potential_rent)


def price_per_sf(price: float | None, rentable_sf: float | None) -> float | None:
    """Return acquisition price per rentable square foot."""
    if not _valid(price, rentable_sf) or not rentable_sf:
        return None
    return float(price) / float(rentable_sf)


def price_per_unit(price: float | None, units: int | None) -> float | None:
    """Return acquisition price per unit."""
    if not _valid(price, units) or not units:
        return None
    return float(price) / int(units)


def price_vs_replacement(
    price_per_sf_value: float | None,
    replacement_cost_per_sf: float | None,
) -> float | None:
    """Return price/SF divided by replacement cost/SF."""
    if not _valid(price_per_sf_value, replacement_cost_per_sf) or not replacement_cost_per_sf:
        return None
    return float(price_per_sf_value) / float(replacement_cost_per_sf)


def mortgage_constant(
    annual_interest_rate: float | None,
    amortization_years: int | None,
) -> float | None:
    """Return annual debt service per dollar of amortizing debt."""
    if not _valid(annual_interest_rate, amortization_years) or not amortization_years:
        return None
    assert annual_interest_rate is not None
    if annual_interest_rate < 0 or amortization_years <= 0:
        return None
    periods = int(amortization_years) * 12
    monthly_rate = annual_interest_rate / 12
    if monthly_rate == 0:
        return 12 / periods
    monthly_payment = monthly_rate / (1 - (1 + monthly_rate) ** -periods)
    return monthly_payment * 12


def annual_debt_service(
    loan_amount: float | None,
    annual_interest_rate: float | None,
    amortization_years: int | None,
) -> float | None:
    """Return annual amortizing debt service."""
    constant = mortgage_constant(annual_interest_rate, amortization_years)
    if not _valid(loan_amount) or constant is None or loan_amount is None or loan_amount < 0:
        return None
    return loan_amount * constant


def cash_on_cash(
    noi_value: float | None,
    annual_debt_service_value: float | None = None,
    equity: float | None = None,
    *,
    price: float | None = None,
    ltv: float = 0.65,
    annual_interest_rate: float | None = None,
    amortization_years: int = 25,
) -> float | None:
    """Return first-year cash flow divided by invested equity as a percentage."""
    if annual_debt_service_value is None or equity is None:
        if not _valid(price, ltv, annual_interest_rate) or price is None:
            return None
        if not 0 <= ltv < 1:
            return None
        equity = price * (1 - ltv)
        annual_debt_service_value = annual_debt_service(
            price * ltv,
            annual_interest_rate,
            amortization_years,
        )
    if not _valid(noi_value, annual_debt_service_value, equity) or not equity:
        return None
    return 100 * (float(noi_value) - float(annual_debt_service_value)) / float(equity)


def dscr(
    noi_value: float | None,
    annual_debt_service_value: float | None,
) -> float | None:
    """Return NOI divided by annual debt service."""
    if not _valid(noi_value, annual_debt_service_value) or not annual_debt_service_value:
        return None
    return float(noi_value) / float(annual_debt_service_value)


def break_even_occupancy(
    operating_expenses: float | None,
    annual_debt_service_value: float | None,
    gross_potential_rent: float | None,
) -> float | None:
    """Return (operating expenses + debt service) / GPR as a percentage."""
    if not _valid(operating_expenses, annual_debt_service_value, gross_potential_rent):
        return None
    if not gross_potential_rent:
        return None
    return 100 * (float(operating_expenses) + float(annual_debt_service_value)) / float(gross_potential_rent)


def walt(leases: Iterable[tuple[float, float] | dict[str, Any]] | None) -> float | None:
    """Return rent-weighted average lease term in years."""
    if leases is None:
        return None
    total_rent = 0.0
    weighted_years = 0.0
    for lease in leases:
        if isinstance(lease, dict):
            rent = lease.get("annual_rent", lease.get("rent"))
            years = lease.get("years_remaining", lease.get("years"))
        else:
            try:
                rent, years = lease
            except (TypeError, ValueError):
                return None
        if not _valid(rent, years) or float(rent) < 0 or float(years) < 0:
            return None
        total_rent += float(rent)
        weighted_years += float(rent) * float(years)
    return weighted_years / total_rent if total_rent else None


def exit_value(
    terminal_noi: float | None,
    entry_cap_rate: float | None,
    exit_cap_spread_bps: float = 50.0,
) -> float | None:
    """Return terminal NOI divided by entry cap plus the exit spread."""
    if not _valid(terminal_noi, entry_cap_rate, exit_cap_spread_bps):
        return None
    exit_cap = float(entry_cap_rate) + float(exit_cap_spread_bps) / 100
    if exit_cap <= 0:
        return None
    return float(terminal_noi) / (exit_cap / 100)


def _irr(cash_flows: Sequence[float] | None) -> float | None:
    if not cash_flows or len(cash_flows) < 2:
        return None
    if not all(math.isfinite(float(value)) for value in cash_flows):
        return None
    if not any(value < 0 for value in cash_flows) or not any(value > 0 for value in cash_flows):
        return None

    def npv(rate: float) -> float:
        return sum(float(value) / ((1 + rate) ** period) for period, value in enumerate(cash_flows))

    low, high = -0.9999, 10.0
    low_value, high_value = npv(low), npv(high)
    while low_value * high_value > 0 and high < 1_000_000:
        high *= 10
        high_value = npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(200):
        midpoint = (low + high) / 2
        midpoint_value = npv(midpoint)
        if abs(midpoint_value) < 1e-9:
            return midpoint * 100
        if low_value * midpoint_value <= 0:
            high = midpoint
        else:
            low = midpoint
            low_value = midpoint_value
    return ((low + high) / 2) * 100


def unlevered_irr(cash_flows: Sequence[float] | None) -> float | None:
    """Return annual unlevered IRR as a percentage."""
    return _irr(cash_flows)


def levered_irr(cash_flows: Sequence[float] | None) -> float | None:
    """Return annual levered IRR as a percentage."""
    return _irr(cash_flows)


def equity_multiple(
    total_distributions: float | None,
    invested_equity: float | None,
) -> float | None:
    """Return total distributions divided by invested equity."""
    if not _valid(total_distributions, invested_equity) or not invested_equity:
        return None
    return float(total_distributions) / float(invested_equity)


def tenant_credit_tier(tenant_name: str | None, rating: str | None = None) -> str | None:
    """Return a supplied credit rating or deterministic tenant-name fallback."""
    if rating and rating.strip():
        return rating.strip().upper()
    if not tenant_name or not tenant_name.strip():
        return None
    normalized = tenant_name.casefold().strip()
    for known_name, known_rating in TENANT_CREDIT_TABLE.items():
        if known_name in normalized:
            return known_rating
    return "unrated"


def _raw_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = raw.get(key)
        if _valid(value):
            return float(value)
    return None


def _assumption(value: Any, source: str) -> dict[str, Any]:
    return {"value": value, "source": source}


def underwrite_listing(
    listing: Listing,
    assumptions: UnderwritingAssumptions | None = None,
) -> UnderwritingResult:
    """Assemble standard metrics from listing facts and explicit assumptions."""
    assumptions = assumptions or UnderwritingAssumptions.for_property_type(
        listing.property_type
    )
    raw = listing.raw
    price = listing.price_usd
    size = listing.size_sqft_num
    units = listing.units
    gross_rent = _raw_number(raw, "gross_potential_rent", "gpr_annual")
    raw_other_income = _raw_number(raw, "other_income")
    other_income = raw_other_income if raw_other_income is not None else 0.0
    operating_expenses = _raw_number(raw, "operating_expenses", "opex")
    assumptions_used: dict[str, dict[str, Any]] = {
        "ltv": _assumption(assumptions.ltv, "assumed"),
        "annual_interest_rate": _assumption(
            assumptions.annual_interest_rate, "assumed"
        ),
        "amortization_years": _assumption(
            assumptions.amortization_years, "assumed"
        ),
        "exit_cap_spread_bps": _assumption(
            assumptions.exit_cap_spread_bps, "assumed"
        ),
    }
    for key, value in (
        ("price", price),
        ("rentable_sf", size),
        ("units", units),
        ("gross_potential_rent", gross_rent),
    ):
        if value is not None:
            assumptions_used[key] = _assumption(value, "listing")
    assumptions_used["other_income"] = _assumption(
        other_income,
        "listing" if raw_other_income is not None else "assumed",
    )
    # Vacancy is resolved before expenses because the expense ratio is applied
    # to effective gross income, not to gross potential rent.
    #
    # It used to be applied to GPR, which overstates expenses by the vacancy
    # fraction of the ratio -- about 6% of NOI at 5% vacancy and a 40% ratio,
    # and biased the same direction every time. Quoting an expense ratio
    # against EGI is the standard convention and is what
    # `underwriting.multifamily` does.
    vacancy = _raw_number(raw, "vacancy_rate")
    if vacancy is None:
        vacancy = assumptions.vacancy_rate
        assumptions_used["vacancy_rate"] = _assumption(vacancy, "assumed")
    else:
        assumptions_used["vacancy_rate"] = _assumption(vacancy, "listing")

    if operating_expenses is None and gross_rent is not None:
        effective_gross_income = gross_rent * (1 - vacancy) + other_income
        operating_expenses = effective_gross_income * assumptions.expense_ratio
        assumptions_used["expense_ratio"] = _assumption(
            assumptions.expense_ratio, "assumed"
        )
        assumptions_used["expense_ratio_basis"] = _assumption(
            "effective_gross_income", "assumed"
        )
    elif operating_expenses is not None:
        assumptions_used["operating_expenses"] = _assumption(
            operating_expenses, "listing"
        )

    noi_value = listing.noi_usd
    if noi_value is not None:
        assumptions_used["noi"] = _assumption(noi_value, "listing")
    elif gross_rent is not None and operating_expenses is not None:
        noi_value = net_operating_income(
            gross_rent,
            vacancy,
            other_income,
            operating_expenses,
        )
        assumptions_used["noi"] = _assumption(noi_value, "derived")
    elif price is not None and listing.cap_rate_pct is not None:
        noi_value = price * listing.cap_rate_pct / 100
        assumptions_used["noi"] = _assumption(noi_value, "derived_from_listing_cap_rate")

    price_sf = price_per_sf(price, size)
    replacement_cost = _raw_number(raw, "replacement_cost_per_sf")
    if replacement_cost is None:
        replacement_cost = assumptions.replacement_cost_per_sf
        if replacement_cost is not None:
            assumptions_used["replacement_cost_per_sf"] = _assumption(
                replacement_cost, "assumed"
            )
    else:
        assumptions_used["replacement_cost_per_sf"] = _assumption(
            replacement_cost, "listing"
        )

    debt_service = None
    equity = None
    if price is not None:
        equity = price * (1 - assumptions.ltv)
        debt_service = annual_debt_service(
            price * assumptions.ltv,
            assumptions.annual_interest_rate,
            assumptions.amortization_years,
        )

    cap = cap_rate(noi_value, price)
    terminal_noi = _raw_number(raw, "terminal_noi", "noi_year_5")
    exit_val = exit_value(
        terminal_noi,
        cap,
        assumptions.exit_cap_spread_bps,
    )
    unlevered_flows = raw.get("unlevered_cash_flows")
    levered_flows = raw.get("levered_cash_flows")
    distributions = _raw_number(raw, "total_distributions")
    leases = raw.get("leases")
    rating = raw.get("tenant_credit_rating")
    tenant = raw.get("tenant_name")

    return UnderwritingResult(
        noi=noi_value,
        cap_rate=cap,
        grm=grm(price, gross_rent),
        price_per_sf=price_sf,
        price_per_unit=price_per_unit(price, units),
        price_vs_replacement=price_vs_replacement(price_sf, replacement_cost),
        cash_on_cash=cash_on_cash(noi_value, debt_service, equity),
        dscr=dscr(noi_value, debt_service),
        break_even_occupancy=break_even_occupancy(
            operating_expenses,
            debt_service,
            gross_rent,
        ),
        walt=walt(leases) if isinstance(leases, list) else None,
        annual_debt_service=debt_service,
        exit_value=exit_val,
        unlevered_irr=unlevered_irr(unlevered_flows) if isinstance(unlevered_flows, list) else None,
        levered_irr=levered_irr(levered_flows) if isinstance(levered_flows, list) else None,
        equity_multiple=equity_multiple(distributions, equity),
        tenant_credit_tier=tenant_credit_tier(
            str(tenant) if tenant else None,
            str(rating) if rating else None,
        ),
        assumptions_used=assumptions_used,
    )
