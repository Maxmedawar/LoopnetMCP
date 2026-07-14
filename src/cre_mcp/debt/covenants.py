"""Forward covenant, cash-trap, and cushion projections."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from cre_mcp.debt.termsheet import (
    NOT_COMPUTABLE,
    QUOTED_TERMS_WARNING,
    TermSheet,
    _number,
    _ratio_decimal,
    _resolve_rate,
)
from cre_mcp.underwriting.metrics import annual_debt_service, dscr


PROJECTION_LABEL = (
    "Projection — not an observed result. NOI, valuation, rate, amortization, and "
    "covenant assumptions are listed in assumption_sheet."
)
VALUATION_REQUIRED = "requires appraisal/valuation input"


def _loan_mapping(loan: TermSheet | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(loan, TermSheet):
        return {
            name: getattr(loan, name)
            for name in loan.__dataclass_fields__
        }
    return dict(loan)


def _growth_decimal(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    number = number / 100 if abs(number) > 1 else number
    return number if number > -1 else None


def _build_noi_path(
    noi_path: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    base_noi: float | None,
    growth: float | None,
    periods: int | None,
    loan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    if isinstance(noi_path, Sequence) and not isinstance(noi_path, (str, bytes)):
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for index, item in enumerate(noi_path):
            if not isinstance(item, Mapping):
                missing.append(f"noi_path[{index}]")
                continue
            noi = _number(item.get("noi"))
            if noi is None:
                missing.append(f"noi_path[{index}].noi")
            rows.append({"period": item.get("period", index + 1), "noi": noi})
        return rows, missing, {"method": "caller-supplied period path"}

    source = dict(noi_path) if isinstance(noi_path, Mapping) else {}
    selected_base = _number(base_noi if base_noi is not None else source.get("base_noi"))
    selected_growth = _growth_decimal(growth if growth is not None else source.get("growth"))
    selected_periods = periods
    if selected_periods is None:
        raw_periods = _number(source.get("periods"))
        if raw_periods is None:
            raw_periods = _number(loan.get("term_years"))
        selected_periods = int(raw_periods) if raw_periods is not None else None
    missing = []
    if selected_base is None:
        missing.append("base_noi")
    if selected_growth is None:
        missing.append("growth")
    if selected_periods is None or selected_periods <= 0:
        missing.append("periods or loan.term_years")
    if missing:
        return [], missing, {
            "method": NOT_COMPUTABLE,
            "base_noi": selected_base,
            "growth": selected_growth,
            "periods": selected_periods,
        }
    assert selected_base is not None and selected_growth is not None and selected_periods is not None
    return [
        {"period": index + 1, "noi": selected_base * (1 + selected_growth) ** index}
        for index in range(selected_periods)
    ], [], {
        "method": "base NOI compounded once per period",
        "base_noi": selected_base,
        "growth": selected_growth,
        "periods": selected_periods,
        "formula": "NOI_t = base_noi * (1 + growth) ** (t - 1)",
    }


def _valuation_lookup(
    valuation_path: Sequence[Mapping[str, Any] | float] | Mapping[Any, Any] | None,
) -> tuple[dict[Any, float | None], list[float | None]]:
    by_period: dict[Any, float | None] = {}
    by_index: list[float | None] = []
    if isinstance(valuation_path, Mapping):
        for period, value in valuation_path.items():
            if isinstance(value, Mapping):
                by_period[period] = _number(value.get("value", value.get("valuation")))
            else:
                by_period[period] = _number(value)
    elif isinstance(valuation_path, Sequence) and not isinstance(valuation_path, (str, bytes)):
        for item in valuation_path:
            if isinstance(item, Mapping):
                value = _number(item.get("value", item.get("valuation")))
                if "period" in item:
                    by_period[item["period"]] = value
                by_index.append(value)
            else:
                by_index.append(_number(item))
    return by_period, by_index


def _period_loan_cash_flow(
    balance: float,
    rate: float,
    monthly_amortizing_payment: float,
    io_months_remaining: int,
) -> tuple[float, float, int]:
    """Project one annual period and its ending balance."""
    io_months = min(max(io_months_remaining, 0), 12)
    amortizing_months = 12 - io_months
    debt_service = balance * rate * io_months / 12
    next_balance = balance
    if amortizing_months:
        monthly_rate = rate / 12
        for _ in range(amortizing_months):
            interest = next_balance * monthly_rate
            principal = min(max(monthly_amortizing_payment - interest, 0.0), next_balance)
            debt_service += interest + principal
            next_balance -= principal
    return debt_service, next_balance, max(io_months_remaining - 12, 0)


def _covenant_levels(covenants: Mapping[str, Any]) -> dict[str, float | None]:
    min_dscr = _number(covenants.get("min_dscr"))
    max_ltv = _ratio_decimal(covenants.get("max_ltv"))
    min_debt_yield = _ratio_decimal(
        covenants.get("min_debt_yield", covenants.get("debt_yield_min"))
    )
    return {
        "min_dscr": min_dscr if min_dscr is not None and min_dscr > 0 else None,
        "max_ltv": max_ltv if max_ltv is not None and max_ltv > 0 else None,
        "min_debt_yield": (
            min_debt_yield if min_debt_yield is not None and min_debt_yield > 0 else None
        ),
    }


def _trigger_test(
    trigger: Any,
    *,
    dscr_value: float | None,
    ltv_value: float | None,
    debt_yield_value: float | None,
) -> tuple[bool | None, str]:
    if trigger is None:
        return None, "cash_sweep_trigger is missing"
    scalar = _number(trigger)
    if scalar is not None:
        if dscr_value is None:
            return None, "DSCR trigger is not computable"
        return dscr_value < scalar, f"DSCR below {scalar:.4f}"
    if not isinstance(trigger, Mapping):
        return None, "cash_sweep_trigger format is not recognized"
    tests: list[bool] = []
    labels: list[str] = []
    dscr_level = _number(
        trigger.get("min_dscr", trigger.get("dscr_below", trigger.get("dscr")))
    )
    if dscr_level is not None:
        if dscr_value is None:
            return None, "DSCR trigger is not computable"
        tests.append(dscr_value < dscr_level)
        labels.append(f"DSCR below {dscr_level:.4f}")
    ltv_level = _ratio_decimal(
        trigger.get("max_ltv", trigger.get("ltv_above", trigger.get("ltv")))
    )
    if ltv_level is not None:
        if ltv_value is None:
            return None, VALUATION_REQUIRED
        tests.append(ltv_value > ltv_level)
        labels.append(f"LTV above {ltv_level:.4%}")
    yield_level = _ratio_decimal(
        trigger.get(
            "min_debt_yield",
            trigger.get("debt_yield_below", trigger.get("debt_yield")),
        )
    )
    if yield_level is not None:
        if debt_yield_value is None:
            return None, "debt-yield trigger is not computable"
        tests.append(debt_yield_value < yield_level)
        labels.append(f"debt yield below {yield_level:.4%}")
    if not tests:
        return None, "cash_sweep_trigger has no recognized covenant level"
    return any(tests), " or ".join(labels)


def _noi_cushion(
    noi: float | None,
    threshold_noi: float | None,
) -> dict[str, Any]:
    if noi is None or threshold_noi is None:
        return {"status": NOT_COMPUTABLE, "amount": None, "pct_of_current_noi": None}
    amount = max(noi - threshold_noi, 0.0)
    return {
        "status": "computed",
        "amount": amount,
        "pct_of_current_noi": amount / noi if noi > 0 else None,
        "breached_now": noi < threshold_noi,
        "threshold_noi": threshold_noi,
    }


def _not_computable(missing: list[str], assumptions: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": NOT_COMPUTABLE,
        "projection_label": PROJECTION_LABEL,
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "missing_inputs": sorted(set(missing)),
        "periods": [],
        "first_breach_period": {"dscr": None, "ltv": None, "debt_yield": None},
        "cash_sweep_activation_timeline": [],
        "early_warnings": [],
        "assumption_sheet": dict(assumptions),
    }


def covenant_forecast(
    loan: TermSheet | Mapping[str, Any],
    noi_path: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    valuation_path: Sequence[Mapping[str, Any] | float] | Mapping[Any, Any] | None = None,
    *,
    base_noi: float | None = None,
    growth: float | None = None,
    periods: int | None = None,
) -> dict[str, Any]:
    """Project covenant compliance using only caller-supplied paths/assumptions."""
    raw = _loan_mapping(loan)
    balance = _number(raw.get("balance", raw.get("proceeds")))
    rate, rate_details, rate_missing = _resolve_rate(raw.get("rate"))
    io_months_raw = _number(raw.get("io_months"))
    amort_years_raw = _number(raw.get("amort_years", raw.get("amort")))
    covenants = raw.get("covenants")
    if not isinstance(covenants, Mapping):
        covenants = {}
    levels = _covenant_levels(covenants)
    path, path_missing, path_assumptions = _build_noi_path(
        noi_path,
        base_noi=base_noi,
        growth=growth,
        periods=periods,
        loan=raw,
    )
    required_missing = list(rate_missing) + path_missing
    if balance is None or balance <= 0:
        required_missing.append("loan.balance or loan.proceeds")
    if io_months_raw is None or io_months_raw < 0 or not io_months_raw.is_integer():
        required_missing.append("loan.io_months")
    if amort_years_raw is None or amort_years_raw <= 0 or not amort_years_raw.is_integer():
        required_missing.append("loan.amort_years")
    if not covenants:
        required_missing.append("loan.covenants")
    assumptions = {
        "projection": PROJECTION_LABEL,
        "noi_path": path_assumptions,
        "rate": rate_details,
        "period_frequency": "annual; each supplied NOI item is one annual period",
        "balance_timing": "covenants use beginning-of-period balance; ending balance rolls forward",
        "breach_rule": "DSCR/debt yield below minimum or LTV above maximum; equality is not a breach",
        "valuation_source": (
            "caller-supplied valuation_path" if valuation_path is not None else VALUATION_REQUIRED
        ),
    }
    if required_missing:
        return _not_computable(required_missing, assumptions)

    assert balance is not None and rate is not None
    assert io_months_raw is not None and amort_years_raw is not None
    io_remaining = int(io_months_raw)
    amort_years = int(amort_years_raw)
    annual_amortizing_payment = annual_debt_service(balance, rate, amort_years)
    if annual_amortizing_payment is None:
        return _not_computable(["loan rate/amortization payment"], assumptions)
    monthly_amortizing_payment = annual_amortizing_payment / 12
    by_period, by_index = _valuation_lookup(valuation_path)
    first_breach: dict[str, Any] = {"dscr": None, "ltv": None, "debt_yield": None}
    first_indices: dict[str, int | None] = {"dscr": None, "ltv": None, "debt_yield": None}
    rows: list[dict[str, Any]] = []
    sweep_timeline: list[dict[str, Any]] = []

    for index, path_row in enumerate(path):
        period = path_row["period"]
        noi = _number(path_row["noi"])
        beginning_balance = balance
        debt_service, ending_balance, io_remaining = _period_loan_cash_flow(
            beginning_balance, rate, monthly_amortizing_payment, io_remaining
        )
        dscr_value = dscr(noi, debt_service)
        debt_yield_value = noi / beginning_balance if noi is not None and beginning_balance > 0 else None
        valuation = by_period.get(period)
        if valuation is None and index < len(by_index):
            valuation = by_index[index]
        ltv_value = beginning_balance / valuation if valuation is not None and valuation > 0 else None
        dscr_breach = (
            dscr_value < levels["min_dscr"]
            if dscr_value is not None and levels["min_dscr"] is not None
            else None
        )
        ltv_breach = (
            ltv_value > levels["max_ltv"]
            if ltv_value is not None and levels["max_ltv"] is not None
            else None
        )
        debt_yield_breach = (
            debt_yield_value < levels["min_debt_yield"]
            if debt_yield_value is not None and levels["min_debt_yield"] is not None
            else None
        )
        for name, breach in (
            ("dscr", dscr_breach),
            ("ltv", ltv_breach),
            ("debt_yield", debt_yield_breach),
        ):
            if breach is True and first_breach[name] is None:
                first_breach[name] = period
                first_indices[name] = index
        sweep_active, sweep_basis = _trigger_test(
            covenants.get("cash_sweep_trigger"),
            dscr_value=dscr_value,
            ltv_value=ltv_value,
            debt_yield_value=debt_yield_value,
        )
        if sweep_active is True:
            sweep_timeline.append({"period": period, "active": True, "basis": sweep_basis})

        dscr_threshold_noi = (
            levels["min_dscr"] * debt_service if levels["min_dscr"] is not None else None
        )
        yield_threshold_noi = (
            levels["min_debt_yield"] * beginning_balance
            if levels["min_debt_yield"] is not None
            else None
        )
        if valuation is not None and levels["max_ltv"] is not None:
            threshold_valuation = beginning_balance / levels["max_ltv"]
            valuation_cushion_amount = max(valuation - threshold_valuation, 0.0)
            valuation_cushion = {
                "status": "computed",
                "amount": valuation_cushion_amount,
                "pct_of_current_valuation": valuation_cushion_amount / valuation,
                "threshold_valuation": threshold_valuation,
                "breached_now": valuation < threshold_valuation,
            }
        else:
            valuation_cushion = {
                "status": (
                    "not_computable: max_ltv covenant level not supplied"
                    if levels["max_ltv"] is None
                    else VALUATION_REQUIRED
                    if valuation is None
                    else NOT_COMPUTABLE
                ),
                "amount": None,
                "pct_of_current_valuation": None,
            }
        rows.append({
            "period": period,
            "projection_label": PROJECTION_LABEL,
            "projected_noi": noi,
            "beginning_balance": beginning_balance,
            "projected_debt_service": debt_service,
            "ending_balance": ending_balance,
            "valuation": valuation,
            "dscr": dscr_value,
            "dscr_covenant": levels["min_dscr"],
            "dscr_breach": dscr_breach,
            "dscr_status": (
                "computed"
                if dscr_breach is not None
                else "not_computable: min_dscr covenant level not supplied"
                if levels["min_dscr"] is None
                else NOT_COMPUTABLE
            ),
            "ltv": ltv_value,
            "ltv_covenant": levels["max_ltv"],
            "ltv_breach": ltv_breach,
            "ltv_status": (
                "computed"
                if ltv_breach is not None
                else "not_computable: max_ltv covenant level not supplied"
                if levels["max_ltv"] is None
                else VALUATION_REQUIRED
            ),
            "debt_yield": debt_yield_value,
            "debt_yield_covenant": levels["min_debt_yield"],
            "debt_yield_breach": debt_yield_breach,
            "debt_yield_status": (
                "computed"
                if debt_yield_breach is not None
                else "not_computable: min_debt_yield covenant level not supplied"
                if levels["min_debt_yield"] is None
                else NOT_COMPUTABLE
            ),
            "cash_sweep_active": sweep_active,
            "cash_sweep_basis": sweep_basis,
            "cushion": {
                "dscr_noi_decline": _noi_cushion(noi, dscr_threshold_noi),
                "debt_yield_noi_decline": _noi_cushion(noi, yield_threshold_noi),
                "ltv_valuation_decline": valuation_cushion,
            },
        })
        balance = ending_balance

    early_warnings: list[dict[str, Any]] = []
    for covenant_name in ("dscr", "ltv", "debt_yield"):
        breach_index = first_indices[covenant_name]
        if breach_index is not None:
            early_warnings.append({
                "covenant": covenant_name,
                "first_breach_period": first_breach[covenant_name],
                "time_to_breach_periods": breach_index + 1,
                "message": f"Projected {covenant_name} breach in period {first_breach[covenant_name]}",
            })
    early_warnings.sort(key=lambda warning: warning["time_to_breach_periods"])
    valuation_note = None
    if valuation_path is None and levels["max_ltv"] is not None:
        valuation_note = VALUATION_REQUIRED
    return {
        "status": "projected",
        "projection_label": PROJECTION_LABEL,
        "warning": QUOTED_TERMS_WARNING,
        "lender_ledger_pointer": "lender_track_record",
        "periods": rows,
        "covenant_levels": levels,
        "covenant_computability": {
            "dscr": "computed" if levels["min_dscr"] is not None else NOT_COMPUTABLE,
            "ltv": (
                "computed"
                if levels["max_ltv"] is not None and valuation_path is not None
                else VALUATION_REQUIRED
                if levels["max_ltv"] is not None
                else NOT_COMPUTABLE
            ),
            "debt_yield": (
                "computed" if levels["min_debt_yield"] is not None else NOT_COMPUTABLE
            ),
        },
        "first_breach_period": first_breach,
        "cash_sweep_activation_timeline": sweep_timeline,
        "early_warnings": early_warnings,
        "valuation_dependent_covenants": valuation_note,
        "missing_inputs": (
            ["valuation_path: requires appraisal/valuation input"] if valuation_note else []
        ),
        "assumption_sheet": assumptions,
    }


__all__ = ["PROJECTION_LABEL", "VALUATION_REQUIRED", "covenant_forecast"]
