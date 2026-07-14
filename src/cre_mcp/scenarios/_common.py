"""Shared, private math helpers for scenario analysis."""

from __future__ import annotations

import math
from typing import Any

from cre_mcp.underwriting.metrics import annual_debt_service

HONESTY_LABEL = (
    "Screening convention, not a prediction. Results only use supplied facts and "
    "the explicitly listed model conventions."
)


def as_number(value: Any) -> float | None:
    """Return a finite float without treating booleans as numbers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        if not cleaned:
            return None
        value = cleaned
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def get_number(values: dict[str, Any], *keys: str) -> float | None:
    """Return the first finite number found under ``keys``."""
    for key in keys:
        number = as_number(values.get(key))
        if number is not None:
            return number
    return None


def decimal_rate(value: Any) -> float | None:
    """Normalize a stated rate: decimals stay decimals and values over one are percent."""
    number = as_number(value)
    if number is None:
        return None
    return number / 100 if abs(number) > 1 else number


def get_rate(values: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in values:
            rate = decimal_rate(values.get(key))
            if rate is not None:
                return rate
    return None


def add_issue(issues: list[str], message: str) -> None:
    """Append a non-computability explanation once."""
    if message not in issues:
        issues.append(message)


def occupancy_from_inputs(deal_inputs: dict[str, Any]) -> float | None:
    occupancy = get_rate(deal_inputs, "occupancy", "occupancy_rate")
    if occupancy is not None:
        return occupancy if 0 <= occupancy <= 1 else None
    vacancy = get_rate(deal_inputs, "vacancy_rate", "vacancy")
    if vacancy is None or not 0 <= vacancy <= 1:
        return None
    return 1 - vacancy


def base_noi(
    deal_inputs: dict[str, Any], issues: list[str], metric: str = "NOI"
) -> tuple[float | None, str | None]:
    """Use stated NOI, or derive it only from a complete component set."""
    stated = get_number(deal_inputs, "noi", "NOI", "noi_usd")
    if stated is not None:
        return stated, "stated_noi"

    gross_rent = get_number(
        deal_inputs, "gross_potential_rent", "gpr", "annual_gross_rent"
    )
    occupancy = occupancy_from_inputs(deal_inputs)
    other_income = get_number(deal_inputs, "other_income")
    operating_expenses = get_number(
        deal_inputs, "operating_expenses", "opex", "annual_operating_expenses"
    )
    missing: list[str] = []
    if gross_rent is None:
        missing.append("gross_potential_rent")
    if occupancy is None:
        missing.append("occupancy or vacancy_rate")
    if other_income is None:
        missing.append("other_income (supply 0 when there is none)")
    if operating_expenses is None:
        missing.append("operating_expenses")
    if missing:
        add_issue(
            issues,
            f"cannot compute {metric} because " + ", ".join(missing) + " is missing",
        )
        return None, None
    assert gross_rent is not None
    assert occupancy is not None
    assert other_income is not None
    assert operating_expenses is not None
    return gross_rent * occupancy + other_income - operating_expenses, "derived_components"


def debt_inputs(
    deal_inputs: dict[str, Any],
    *,
    rate_delta: float = 0.0,
    issues: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve debt without supplying financing facts the caller omitted."""
    issues = issues if issues is not None else []
    price = get_number(deal_inputs, "price", "purchase_price", "acquisition_price")
    loan_amount = get_number(deal_inputs, "loan_amount", "debt_amount")
    ltv = get_rate(deal_inputs, "ltv", "loan_to_value")
    loan_source: str | None = None
    if loan_amount is not None:
        loan_source = "loan_amount"
    elif ltv is not None and price is not None:
        loan_amount = price * ltv
        loan_source = "price_times_ltv"
    elif ltv is not None:
        add_issue(issues, "cannot compute loan amount because price is missing")
    else:
        add_issue(
            issues,
            "cannot compute debt metrics because loan_amount or ltv is missing; "
            "supply loan_amount=0 or ltv=0 for an all-cash deal",
        )

    if loan_amount is not None and loan_amount < 0:
        add_issue(issues, "cannot compute debt metrics because loan_amount is negative")
        loan_amount = None

    rate = get_rate(
        deal_inputs, "annual_interest_rate", "interest_rate", "rate"
    )
    amortization = get_number(
        deal_inputs, "amortization_years", "amort_years", "amort"
    )
    io_months = get_number(deal_inputs, "io_months", "interest_only_months")
    if io_months is None:
        io_source = None
    else:
        io_source = "supplied"

    if loan_amount is not None and loan_amount > 0:
        if rate is None:
            add_issue(issues, "cannot compute debt service because interest_rate is missing")
        elif rate + rate_delta < 0:
            add_issue(
                issues,
                "cannot compute debt service because shocked interest_rate is negative",
            )
        if amortization is None:
            add_issue(
                issues, "cannot compute debt service because amortization_years is missing"
            )
        elif amortization <= 0:
            add_issue(
                issues,
                "cannot compute debt service because amortization_years must be positive",
            )
            amortization = None
        if io_months is None:
            add_issue(
                issues,
                "cannot compute debt service because io_months is missing; supply 0 "
                "when the loan amortizes immediately",
            )
        elif io_months < 0:
            add_issue(issues, "cannot compute debt service because io_months is negative")
            io_months = None

    shocked_rate = rate + rate_delta if rate is not None else None
    payment = None
    if (
        loan_amount is not None
        and loan_amount > 0
        and shocked_rate is not None
        and shocked_rate >= 0
        and amortization is not None
        and amortization > 0
        and io_months is not None
    ):
        annual_payment = annual_debt_service(
            loan_amount, shocked_rate, int(amortization)
        )
        payment = annual_payment / 12 if annual_payment is not None else None
    elif loan_amount == 0:
        payment = 0.0

    return {
        "price": price,
        "loan_amount": loan_amount,
        "loan_source": loan_source,
        "ltv": ltv,
        "annual_interest_rate": shocked_rate,
        "base_annual_interest_rate": rate,
        "amortization_years": int(amortization) if amortization is not None else None,
        "io_months": int(io_months) if io_months is not None else None,
        "io_months_source": io_source,
        "monthly_amortizing_payment": payment,
    }


def monthly_debt_service(debt: dict[str, Any], month: int) -> float | None:
    """Return debt service in one-based ``month``."""
    loan = debt.get("loan_amount")
    if loan == 0:
        return 0.0
    rate = debt.get("annual_interest_rate")
    payment = debt.get("monthly_amortizing_payment")
    if loan is None or rate is None or payment is None:
        return None
    io_months = debt.get("io_months")
    if io_months is None:
        return None
    if month <= io_months:
        return loan * rate / 12
    return payment


def loan_balance(debt: dict[str, Any], elapsed_months: int) -> float | None:
    """Return balance after IO and subsequent level-payment amortization."""
    loan = debt.get("loan_amount")
    if loan == 0:
        return 0.0
    rate = debt.get("annual_interest_rate")
    amortization = debt.get("amortization_years")
    payment = debt.get("monthly_amortizing_payment")
    if loan is None or rate is None or amortization is None or payment is None:
        return None
    io_months = debt.get("io_months")
    if io_months is None:
        return None
    amortizing_months = max(0, elapsed_months - io_months)
    total_months = amortization * 12
    if amortizing_months >= total_months:
        return 0.0
    if amortizing_months == 0:
        return loan
    monthly_rate = rate / 12
    if monthly_rate == 0:
        return max(0.0, loan - payment * amortizing_months)
    balance = loan * (1 + monthly_rate) ** amortizing_months - payment * (
        ((1 + monthly_rate) ** amortizing_months - 1) / monthly_rate
    )
    return max(0.0, balance)


def first_year_debt_service(debt: dict[str, Any]) -> float | None:
    payments = [monthly_debt_service(debt, month) for month in range(1, 13)]
    if any(payment is None for payment in payments):
        return None
    return sum(float(payment) for payment in payments)


def normalized_assumptions(deal_inputs: dict[str, Any]) -> dict[str, Any]:
    """Echo the caller's inputs and the model-scope conventions."""
    return {
        "supplied_deal_inputs": dict(deal_inputs),
        "model_conventions": [
            "NOI is level through the hold; no growth is inferred.",
            "Sale costs, taxes, capital expenditures, and financing fees are excluded.",
            "Debt amortizes monthly after any stated IO period.",
            "Rate shocks reprice the full loan immediately for screening purposes.",
            "Percent-like rates over 1 are normalized as percentages; e.g. 7 means 7%.",
        ],
    }
