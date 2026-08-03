"""Conditional value of assumable debt versus same-balance market debt."""

from __future__ import annotations

from typing import Any, Mapping

from cre_mcp.debt.covenants import PROJECTION_LABEL
from cre_mcp.debt.termsheet import (
    NOT_COMPUTABLE,
    QUOTED_TERMS_WARNING,
    _fee_pct_decimal,
    _number,
    _rate_decimal,
    _ratio_decimal,
)
from cre_mcp.underwriting.metrics import annual_debt_service


ASSUMABLE_METHOD = (
    "Monthly payment savings compare the existing loan with a hypothetical market-rate "
    "loan on the same opening balance. Each monthly delta is discounted at the supplied "
    "market note rate. At the comparison horizon, the discounted difference in remaining "
    "principal is added so different amortization schedules are compared consistently."
)


def _field(source: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in source:
            return source[name]
    return None


def _integer(value: Any, *, positive: bool = False) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    result = int(number)
    if positive and result <= 0:
        return None
    if not positive and result < 0:
        return None
    return result


def _years(value: Any) -> float | None:
    if isinstance(value, Mapping):
        if value.get("years") is not None:
            value = value["years"]
        elif value.get("months") is not None:
            months = _number(value["months"])
            return months / 12 if months is not None and months > 0 else None
    number = _number(value)
    return number if number is not None and number > 0 else None


def _assumption_fee(value: Any, balance: float | None) -> tuple[float | None, str]:
    if isinstance(value, Mapping):
        amount = _number(value.get("amount"))
        if amount is not None and amount >= 0:
            return amount, "caller-supplied dollar amount"
        pct = _fee_pct_decimal(value.get("pct", value.get("percent")))
        if pct is not None and balance is not None:
            return balance * pct, "caller-supplied percentage of assumed balance"
        return None, NOT_COMPUTABLE
    amount = _number(value)
    if amount is not None and amount >= 0:
        return amount, "numeric assumption_fee treated as dollars"
    return None, NOT_COMPUTABLE


def _schedule(
    *,
    principal: float,
    rate: float,
    io_months: int,
    amort_years: int,
    months: int,
) -> list[dict[str, float | int]]:
    balance = principal
    amortizing_annual = annual_debt_service(principal, rate, amort_years)
    if amortizing_annual is None:
        raise ValueError("rate and amortization cannot produce a payment schedule")
    monthly_payment = amortizing_annual / 12
    monthly_rate = rate / 12
    rows: list[dict[str, float | int]] = []
    for month in range(1, months + 1):
        beginning_balance = balance
        interest = balance * monthly_rate
        if month <= io_months:
            principal_payment = 0.0
            payment = interest
        else:
            principal_payment = min(max(monthly_payment - interest, 0.0), balance)
            payment = interest + principal_payment
            balance -= principal_payment
        rows.append({
            "month": month,
            "beginning_balance": beginning_balance,
            "payment": payment,
            "interest": interest,
            "principal": principal_payment,
            "ending_balance": balance,
        })
    return rows


def _not_computable(
    missing: list[str],
    existing_loan: Mapping[str, Any],
    market: Mapping[str, Any],
    price: Any,
    hold_years: Any,
) -> dict[str, Any]:
    return {
        "status": NOT_COMPUTABLE,
        "projection_label": PROJECTION_LABEL,
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "missing_inputs": sorted(set(missing)),
        "pv_payment_savings": None,
        "net_assumable_debt_value": None,
        "effective_price_adjustment": None,
        "proceeds_gap_vs_new_debt": None,
        "equity_gap": None,
        "net_verdict_range": None,
        "assumption_risks": [
            "Lender consent is required and is not predicted.",
            "Consent timing may affect closing and is not predicted.",
            "Release of the prior guarantor must be documented; it is not assumed.",
        ],
        "assumption_sheet": {
            "existing_loan": dict(existing_loan),
            "market": dict(market),
            "price": price,
            "hold_years": hold_years,
            "method": ASSUMABLE_METHOD,
        },
    }


def value_assumable_debt(
    existing_loan: Mapping[str, Any],
    market: Mapping[str, Any],
    price: float | None,
    hold_years: float | None,
) -> dict[str, Any]:
    """Value an assumption conditional on lender consent, with no approval probability."""
    balance = _number(existing_loan.get("balance"))
    existing_rate = _rate_decimal(existing_loan.get("rate"))
    existing_io = _integer(
        _field(existing_loan, "io_remaining_months", "io_remaining")
    )
    existing_amort = _integer(
        _field(existing_loan, "amort_years", "amort"), positive=True
    )
    maturity_years = _years(_field(existing_loan, "maturity_years", "maturity"))
    fee, fee_basis = _assumption_fee(existing_loan.get("assumption_fee"), balance)
    market_rate = _rate_decimal(market.get("rate"))
    market_ltv = _ratio_decimal(market.get("ltv"))
    market_io = _integer(_field(market, "io_months", "io"))
    market_amort = _integer(_field(market, "amort_years", "amort"), positive=True)
    selected_price = _number(price)
    selected_hold = _years(hold_years)
    missing: list[str] = []
    for name, value in (
        ("existing_loan.balance", balance),
        ("existing_loan.rate", existing_rate),
        ("existing_loan.io_remaining", existing_io),
        ("existing_loan.amort", existing_amort),
        ("existing_loan.maturity", maturity_years),
        ("existing_loan.assumption_fee", fee),
        ("market.rate", market_rate),
        ("market.ltv", market_ltv),
        ("market.io", market_io),
        ("market.amort", market_amort),
        ("price", selected_price),
        ("hold_years", selected_hold),
    ):
        if value is None:
            missing.append(name)
    if balance is not None and balance <= 0:
        missing.append("existing_loan.balance (positive required)")
    if selected_price is not None and selected_price <= 0:
        missing.append("price (positive required)")
    if missing:
        return _not_computable(missing, existing_loan, market, price, hold_years)

    assert balance is not None and existing_rate is not None and existing_io is not None
    assert existing_amort is not None and maturity_years is not None and fee is not None
    assert market_rate is not None and market_ltv is not None and market_io is not None
    assert market_amort is not None and selected_price is not None and selected_hold is not None
    hold_months = max(int(round(selected_hold * 12)), 1)
    maturity_months = max(int(round(maturity_years * 12)), 1)
    comparison_months = min(hold_months, maturity_months)
    existing_schedule = _schedule(
        principal=balance,
        rate=existing_rate,
        io_months=existing_io,
        amort_years=existing_amort,
        months=comparison_months,
    )
    market_schedule = _schedule(
        principal=balance,
        rate=market_rate,
        io_months=market_io,
        amort_years=market_amort,
        months=comparison_months,
    )
    monthly_discount_rate = market_rate / 12
    savings_rows: list[dict[str, Any]] = []
    pv_payments = 0.0
    for existing_row, market_row in zip(existing_schedule, market_schedule):
        month = int(existing_row["month"])
        payment_saving = float(market_row["payment"]) - float(existing_row["payment"])
        discount_factor = (1 + monthly_discount_rate) ** month
        pv_saving = payment_saving / discount_factor
        pv_payments += pv_saving
        savings_rows.append({
            "month": month,
            "projection_label": PROJECTION_LABEL,
            "existing_payment": existing_row["payment"],
            "market_payment": market_row["payment"],
            "payment_saving": payment_saving,
            "discount_factor": discount_factor,
            "pv_payment_saving": pv_saving,
        })
    existing_ending_balance = float(existing_schedule[-1]["ending_balance"])
    market_ending_balance = float(market_schedule[-1]["ending_balance"])
    terminal_balance_adjustment = (
        market_ending_balance - existing_ending_balance
    ) / ((1 + monthly_discount_rate) ** comparison_months)
    gross_value = pv_payments + terminal_balance_adjustment
    net_value = gross_value - fee
    market_new_debt = selected_price * market_ltv
    proceeds_gap = market_new_debt - balance
    equity_gap = max(proceeds_gap, 0.0)
    approval_note = existing_loan.get("approval_risk_note")
    risks = [
        "Lender consent is required; this analysis assigns no approval probability.",
        "Consent and document-review timing may delay or prevent closing.",
        "Release of the prior guarantor must be explicit; it is not assumed.",
        "Loan documents may impose assumption conditions, reserves, tests, or fees not supplied here.",
    ]
    if approval_note:
        risks.append(f"Caller-supplied approval risk: {approval_note}")
    else:
        risks.append("approval_risk_note is missing; deal-specific consent risk is not assessed.")
    return {
        "status": "projected",
        "projection_label": PROJECTION_LABEL,
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "method": ASSUMABLE_METHOD,
        "comparison_months": comparison_months,
        "pv_payment_savings_before_terminal_adjustment": pv_payments,
        "terminal_balance_adjustment": terminal_balance_adjustment,
        "pv_payment_savings": gross_value,
        "assumption_fee": fee,
        "net_assumable_debt_value": net_value,
        "effective_price_adjustment": net_value,
        "effective_price_adjustment_basis": (
            "positive means modeled debt benefit/premium capacity; debt-adjusted effective "
            "purchase price subtracts this benefit from stated price"
        ),
        "debt_adjusted_effective_price": selected_price - net_value,
        "price_premium_capacity_if_approved": max(net_value, 0.0),
        "market_new_debt_proceeds": market_new_debt,
        "assumable_balance": balance,
        "proceeds_gap_vs_new_debt": proceeds_gap,
        "equity_gap": equity_gap,
        "assumption_risks": risks,
        "net_verdict_range": {
            "low": min(0.0, net_value),
            "high": max(0.0, net_value),
            "basis": (
                "conditional endpoints only: zero debt value if consent fails versus modeled net "
                "value if consent succeeds; no approval probability or expected value is assigned"
            ),
            "if_not_approved": 0.0,
            "if_approved": net_value,
        },
        "payment_savings_schedule": savings_rows,
        "existing_loan_schedule": [
            {**row, "projection_label": PROJECTION_LABEL} for row in existing_schedule
        ],
        "market_loan_schedule": [
            {**row, "projection_label": PROJECTION_LABEL} for row in market_schedule
        ],
        "missing_inputs": ([] if approval_note else ["existing_loan.approval_risk_note"]),
        "assumption_sheet": {
            "existing_loan": dict(existing_loan),
            "market": dict(market),
            "price": selected_price,
            "hold_years": selected_hold,
            "comparison_horizon": (
                "earlier of hold period and stated existing-loan maturity; maturity is interpreted "
                "as years unless supplied as {'months': N}"
            ),
            "io_units": "io_remaining and market.io are interpreted as months",
            "assumption_fee_basis": fee_basis,
            "discount_rate": "supplied market note rate, compounded monthly",
            "new_debt_comparison_balance": "same opening balance as the assumable loan",
            "proceeds_gap_basis": "price * supplied market LTV minus assumable balance",
            "unmodeled": [
                "approval probability",
                "lender legal/processing costs not supplied",
                "tax effects",
                "future refinance after existing maturity",
                "rate changes on floating debt",
            ],
        },
    }


__all__ = ["ASSUMABLE_METHOD", "value_assumable_debt"]
