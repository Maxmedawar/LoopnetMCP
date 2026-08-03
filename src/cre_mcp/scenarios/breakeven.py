"""Break-even thresholds from supplied deal and debt facts."""

from __future__ import annotations

from typing import Any

from cre_mcp.scenarios._common import (
    HONESTY_LABEL,
    add_issue,
    base_noi,
    debt_inputs,
    first_year_debt_service,
    get_number,
    loan_balance,
    monthly_debt_service,
    normalized_assumptions,
    occupancy_from_inputs,
)
from cre_mcp.underwriting.metrics import (
    annual_debt_service,
    break_even_occupancy,
)


def _service_at_rate(
    loan_amount: float,
    rate: float,
    amortization_years: int,
    io_months: int,
) -> float | None:
    amortizing = annual_debt_service(loan_amount, rate, amortization_years)
    if amortizing is None:
        return None
    io_in_year = min(12, max(0, io_months))
    return loan_amount * rate / 12 * io_in_year + amortizing / 12 * (12 - io_in_year)


def _rate_ceiling(
    noi: float | None,
    target_dscr: float,
    debt: dict[str, Any],
) -> tuple[float | None, str | None]:
    loan = debt.get("loan_amount")
    amortization = debt.get("amortization_years")
    io_months = debt.get("io_months")
    if loan == 0:
        return None, "cannot compute rate ceiling because the deal has no debt"
    if loan is None or amortization is None or io_months is None:
        return (
            None,
            "cannot compute rate ceiling because loan, amortization, or io_months is missing",
        )
    if noi is None:
        return None, "cannot compute rate ceiling because NOI is missing"
    if noi <= 0 or target_dscr <= 0:
        return None, "cannot compute rate ceiling because NOI and target DSCR must be positive"
    allowed_service = noi / target_dscr
    zero_service = _service_at_rate(
        loan, 0.0, amortization, io_months
    )
    if zero_service is None or zero_service > allowed_service:
        return (
            None,
            "cannot compute a non-negative rate ceiling because DSCR fails even at 0%",
        )
    low, high = 0.0, 1.0
    while high < 100:
        service = _service_at_rate(
            loan, high, amortization, io_months
        )
        if service is None or service >= allowed_service:
            break
        high *= 2
    high = min(high, 100.0)
    high_service = _service_at_rate(
        loan, high, amortization, io_months
    )
    if high_service is None or high_service < allowed_service:
        return None, "cannot bracket rate ceiling below 10,000%"
    for _ in range(160):
        midpoint = (low + high) / 2
        service = _service_at_rate(
            loan, midpoint, amortization, io_months
        )
        if service is None:
            return None, "cannot compute rate ceiling because debt service is unavailable"
        if service <= allowed_service:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2, None


def analyze_breakevens(
    deal_inputs: dict[str, Any], target_dscr: float | None = None
) -> dict[str, Any]:
    """Compute deal thresholds without inventing missing rent, size, or debt facts.

    Occupancy uses the existing underwriting ``break_even_occupancy`` function
    and is returned as a percentage. Rate ceilings are decimal annual rates.
    Break-even exit price is the undiscounted gross sale price needed to recover
    initial equity after cumulative level-NOI hold cash flow; sale costs are out
    of scope and are not silently estimated.
    """
    if not isinstance(deal_inputs, dict):
        raise TypeError("deal_inputs must be a dict")
    issues: list[str] = []
    noi, noi_source = base_noi(deal_inputs, issues)
    debt = debt_inputs(deal_inputs, issues=issues)
    annual_service = first_year_debt_service(debt)
    loan = debt.get("loan_amount")
    if loan is not None and loan > 0 and annual_service is None:
        add_issue(issues, "cannot compute break-even NOI because debt service is unavailable")

    supplied_target = target_dscr
    if supplied_target is None:
        supplied_target = get_number(deal_inputs, "target_dscr")
    if supplied_target is None:
        add_issue(
            issues,
            "cannot compute target-DSCR break-evens because target_dscr is missing",
        )
    elif supplied_target <= 0:
        add_issue(
            issues,
            "cannot compute target-DSCR break-evens because target_dscr must be positive",
        )
        supplied_target = None

    break_even_noi = annual_service if annual_service is not None and loan != 0 else None
    target_noi = (
        annual_service * supplied_target
        if annual_service is not None
        and loan != 0
        and supplied_target is not None
        else None
    )
    if loan == 0:
        add_issue(issues, "cannot compute debt break-evens because the deal has no debt")

    gross_rent = get_number(
        deal_inputs, "gross_potential_rent", "gpr", "annual_gross_rent"
    )
    operating_expenses = get_number(
        deal_inputs, "operating_expenses", "opex", "annual_operating_expenses"
    )
    other_income = get_number(deal_inputs, "other_income")
    occupancy = occupancy_from_inputs(deal_inputs)
    rentable_sf = get_number(
        deal_inputs, "rentable_sf", "square_feet", "size_sqft", "sf"
    )
    break_even_occ = break_even_occupancy(
        operating_expenses, annual_service, gross_rent
    )
    if break_even_occ is None:
        add_issue(
            issues,
            "cannot compute break-even occupancy because operating_expenses, "
            "debt service, or gross_potential_rent is missing or invalid",
        )

    def rent_threshold(required_noi: float | None) -> float | None:
        if (
            required_noi is None
            or operating_expenses is None
            or other_income is None
            or occupancy is None
            or occupancy <= 0
            or rentable_sf is None
            or rentable_sf <= 0
        ):
            return None
        annual_gpr = (required_noi + operating_expenses - other_income) / occupancy
        return annual_gpr / rentable_sf

    break_even_rent = rent_threshold(break_even_noi)
    target_rent = rent_threshold(target_noi)
    if break_even_rent is None:
        add_issue(
            issues,
            "cannot compute break-even rent/psf because occupancy, rentable_sf, "
            "other_income, operating_expenses, or debt service is missing or invalid",
        )

    hold_years = get_number(deal_inputs, "hold_years")
    price = debt.get("price")
    break_even_exit_price = None
    remaining_balance = None
    if hold_years is None:
        add_issue(issues, "cannot compute break-even exit price because hold_years is missing")
    elif hold_years < 0:
        add_issue(
            issues, "cannot compute break-even exit price because hold_years is negative"
        )
    elif price is None:
        add_issue(issues, "cannot compute break-even exit price because price is missing")
    elif loan is None:
        add_issue(
            issues, "cannot compute break-even exit price because loan_amount is missing"
        )
    elif noi is None:
        add_issue(issues, "cannot compute break-even exit price because NOI is missing")
    else:
        hold_months = round(hold_years * 12)
        remaining_balance = loan_balance(debt, hold_months)
        if remaining_balance is None:
            add_issue(
                issues,
                "cannot compute break-even exit price because debt terms are incomplete",
            )
        else:
            pre_sale_cash = 0.0
            complete = True
            for month in range(1, hold_months + 1):
                service = monthly_debt_service(debt, month)
                if service is None:
                    complete = False
                    break
                pre_sale_cash += noi / 12 - service
            if complete:
                initial_equity = price - loan
                break_even_exit_price = max(
                    0.0, remaining_balance + initial_equity - pre_sale_cash
                )

    ceiling_1, ceiling_1_issue = _rate_ceiling(noi, 1.0, debt)
    if ceiling_1_issue:
        add_issue(issues, ceiling_1_issue)
    target_ceiling = None
    if supplied_target is not None:
        target_ceiling, target_issue = _rate_ceiling(noi, supplied_target, debt)
        if target_issue:
            add_issue(issues, target_issue.replace("rate ceiling", "target rate ceiling"))

    assumptions = normalized_assumptions(deal_inputs)
    assumptions.update(
        {
            "noi_source": noi_source,
            "debt_terms": debt,
            "target_dscr": supplied_target,
            "rent_per_sf_basis": "annual gross potential rent per rentable SF",
            "break_even_exit_price_basis": (
                "undiscounted equity recovery; gross price with no sale costs"
            ),
        }
    )
    return {
        "honesty_label": HONESTY_LABEL,
        "break_even_rent_per_sf": break_even_rent,
        "target_dscr_rent_per_sf": target_rent,
        "break_even_noi": break_even_noi,
        "target_dscr_noi": target_noi,
        "break_even_exit_price": break_even_exit_price,
        "remaining_loan_balance_at_exit": remaining_balance,
        "break_even_occupancy": break_even_occ,
        "break_even_occupancy_percent": break_even_occ,
        "rate_ceiling_dscr_1_0": ceiling_1,
        "rate_ceiling_dscr_1_0_percent": ceiling_1 * 100 if ceiling_1 is not None else None,
        "target_dscr": supplied_target,
        "rate_ceiling_target_dscr": target_ceiling,
        "rate_ceiling_target_dscr_percent": (
            target_ceiling * 100 if target_ceiling is not None else None
        ),
        "assumptions": assumptions,
        "not_computable": issues,
    }
