"""Explicit commercial-real-estate scenario and stress calculations.

Preset scenarios are screening CONVENTIONS, not predictions:

* ``base``: no shock.
* ``downside``: rent -10%, operating expenses +10%, exit cap +100 bps.
* ``severe``: rent -20%, operating expenses +15%, exit cap +200 bps,
  interest rate +150 bps.
* ``lender``: vacancy floor 10%, management-fee floor 3% of effective rental
  income, and annual replacement reserves of $0.25/SF. The management fee and
  reserves are added to stated expenses; callers should identify possible
  double-counting during diligence.

No preset has a probability attached. Missing facts are never filled with
market guesses; dependent metrics are returned as ``None`` with a specific
``cannot compute ... because ...`` explanation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.scenarios._common import (
    HONESTY_LABEL,
    add_issue,
    as_number,
    base_noi,
    debt_inputs,
    decimal_rate,
    first_year_debt_service,
    get_number,
    get_rate,
    loan_balance,
    monthly_debt_service,
    normalized_assumptions,
    occupancy_from_inputs,
)
from cre_mcp.underwriting.metrics import (
    break_even_occupancy,
    cash_on_cash,
    dscr,
    equity_multiple,
    levered_irr,
    mortgage_constant,
)

SCENARIO_PRESETS: dict[str, dict[str, Any]] = {
    "base": {
        "shocks": {},
        "label": "CONVENTION: unshocked stated case; not a prediction",
    },
    "downside": {
        "shocks": {"rent": -0.10, "opex": 0.10, "exit_cap_bps": 100},
        "label": "CONVENTION: illustrative downside; not a prediction",
    },
    "severe": {
        "shocks": {
            "rent": -0.20,
            "opex": 0.15,
            "exit_cap_bps": 200,
            "interest_rate_bps": 150,
        },
        "label": "CONVENTION: illustrative severe stress; not a prediction",
    },
    "lender": {
        "shocks": {
            "vacancy_floor": 0.10,
            "management_fee_floor": 0.03,
            "reserves_per_sf": 0.25,
        },
        "label": "CONVENTION: illustrative lender underwriting; not a quote or approval",
    },
}

_SHOCK_KEYS = {
    "occupancy",
    "occupancy_delta",
    "rent",
    "rent_delta",
    "opex",
    "opex_delta",
    "interest_rate",
    "interest_rate_delta",
    "interest_rate_bps",
    "exit_cap",
    "exit_cap_delta",
    "exit_cap_bps",
    "hold_years",
    "hold_years_delta",
    "sale_timing",
    "sale_timing_months",
    "vacancy_floor",
    "management_fee_floor",
    "reserves_per_sf",
}


def _relative_delta(value: Any) -> float:
    number = as_number(value)
    if number is None:
        return 0.0
    return number / 100 if abs(number) > 1 else number


def _rate_delta(shocks: Mapping[str, Any], key: str) -> float:
    bps = as_number(shocks.get(f"{key}_bps"))
    if bps is not None:
        return bps / 10_000
    for candidate in (key, f"{key}_delta"):
        if candidate in shocks:
            return _relative_delta(shocks.get(candidate))
    return 0.0


def _normalize_shocks(shocks: Mapping[str, Any]) -> dict[str, float | None]:
    hold_delta = get_number(dict(shocks), "hold_years", "hold_years_delta") or 0.0
    sale_timing = get_number(dict(shocks), "sale_timing_months", "sale_timing") or 0.0
    vacancy_floor = (
        decimal_rate(shocks.get("vacancy_floor"))
        if "vacancy_floor" in shocks
        else None
    )
    management_fee = (
        decimal_rate(shocks.get("management_fee_floor"))
        if "management_fee_floor" in shocks
        else None
    )
    return {
        "occupancy_delta": _rate_delta(shocks, "occupancy"),
        "rent_delta": _relative_delta(
            shocks.get("rent", shocks.get("rent_delta", 0.0))
        ),
        "opex_delta": _relative_delta(
            shocks.get("opex", shocks.get("opex_delta", 0.0))
        ),
        "interest_rate_delta": _rate_delta(shocks, "interest_rate"),
        "exit_cap_delta": _rate_delta(shocks, "exit_cap"),
        "hold_years_delta": hold_delta,
        "sale_timing_months": sale_timing,
        "vacancy_floor": vacancy_floor,
        "management_fee_floor": management_fee,
        "reserves_per_sf": as_number(shocks.get("reserves_per_sf")),
    }


def _stressed_noi(
    deal_inputs: dict[str, Any],
    shock: dict[str, float | None],
    issues: list[str],
) -> tuple[float | None, dict[str, Any]]:
    noi, source = base_noi(deal_inputs, issues)
    bridge: dict[str, Any] = {"base_noi": noi, "base_noi_source": source}
    if noi is None:
        return None, bridge

    rent_delta = float(shock["rent_delta"] or 0.0)
    occupancy_delta = float(shock["occupancy_delta"] or 0.0)
    opex_delta = float(shock["opex_delta"] or 0.0)
    vacancy_floor = shock["vacancy_floor"]
    management_fee_floor = shock["management_fee_floor"]
    reserves_per_sf = shock["reserves_per_sf"]
    needs_rental_bridge = any(
        value not in (None, 0.0)
        for value in (rent_delta, occupancy_delta, vacancy_floor, management_fee_floor)
    )
    gross_rent = get_number(
        deal_inputs, "gross_potential_rent", "gpr", "annual_gross_rent"
    )
    occupancy = occupancy_from_inputs(deal_inputs)
    operating_expenses = get_number(
        deal_inputs, "operating_expenses", "opex", "annual_operating_expenses"
    )
    rentable_sf = get_number(
        deal_inputs, "rentable_sf", "square_feet", "size_sqft", "sf"
    )

    missing: list[str] = []
    if needs_rental_bridge and gross_rent is None:
        missing.append("gross_potential_rent")
    if needs_rental_bridge and occupancy is None:
        missing.append("occupancy or vacancy_rate")
    if opex_delta != 0 and operating_expenses is None:
        missing.append("operating_expenses")
    if reserves_per_sf not in (None, 0.0) and rentable_sf is None:
        missing.append("rentable_sf")
    if missing:
        add_issue(
            issues,
            "cannot compute stressed NOI because " + ", ".join(missing) + " is missing",
        )
        return None, bridge

    stressed_noi = noi
    stressed_occupancy = occupancy
    rental_income_change = 0.0
    management_fee = 0.0
    if needs_rental_bridge:
        assert gross_rent is not None
        assert occupancy is not None
        stressed_occupancy = max(0.0, min(1.0, occupancy + occupancy_delta))
        if vacancy_floor is not None:
            stressed_occupancy = min(stressed_occupancy, 1 - vacancy_floor)
        base_rental_income = gross_rent * occupancy
        stressed_rental_income = gross_rent * (1 + rent_delta) * stressed_occupancy
        rental_income_change = stressed_rental_income - base_rental_income
        stressed_noi += rental_income_change
        if management_fee_floor is not None:
            management_fee = stressed_rental_income * management_fee_floor
            stressed_noi -= management_fee

    expense_change = 0.0
    if opex_delta != 0:
        assert operating_expenses is not None
        expense_change = operating_expenses * opex_delta
        stressed_noi -= expense_change

    reserves = 0.0
    if reserves_per_sf not in (None, 0.0):
        assert rentable_sf is not None
        reserves = rentable_sf * float(reserves_per_sf)
        stressed_noi -= reserves

    bridge.update(
        {
            "base_occupancy": occupancy,
            "stressed_occupancy": stressed_occupancy,
            "rental_income_change": rental_income_change,
            "operating_expense_change": expense_change,
            "management_fee_floor_expense": management_fee,
            "replacement_reserves": reserves,
            "stressed_noi": stressed_noi,
        }
    )
    return stressed_noi, bridge


def _effective_hold_months(
    deal_inputs: dict[str, Any], shock: dict[str, float | None], issues: list[str]
) -> int | None:
    hold_years = get_number(deal_inputs, "hold_years")
    if hold_years is None:
        add_issue(issues, "cannot compute IRR because hold_years is missing")
        return None
    months = round(
        (hold_years + float(shock["hold_years_delta"] or 0.0)) * 12
        + float(shock["sale_timing_months"] or 0.0)
    )
    if months <= 0:
        add_issue(
            issues,
            "cannot compute IRR because shocked hold period must be greater than zero",
        )
        return None
    return months


def _refi_ability(
    deal_inputs: dict[str, Any],
    noi: float | None,
    exit_value: float | None,
    remaining_balance: float | None,
    debt: dict[str, Any],
    issues: list[str],
) -> tuple[bool | None, dict[str, Any]]:
    target_dscr = get_number(deal_inputs, "refi_target_dscr", "target_dscr")
    max_ltv = get_rate(deal_inputs, "max_refi_ltv", "refi_ltv")
    detail: dict[str, Any] = {
        "target_dscr": target_dscr,
        "max_refi_ltv": max_ltv,
        "maximum_refinance_proceeds": None,
        "remaining_loan_balance": remaining_balance,
    }
    missing = []
    if target_dscr is None:
        missing.append("refi_target_dscr")
    if max_ltv is None:
        missing.append("max_refi_ltv")
    if missing:
        add_issue(
            issues,
            "cannot compute refi-ability because " + ", ".join(missing) + " is missing",
        )
        return None, detail
    if remaining_balance == 0:
        add_issue(issues, "cannot compute refi-ability because the deal has no debt")
        return None, detail
    rate = debt.get("annual_interest_rate")
    amortization = debt.get("amortization_years")
    if (
        noi is None
        or exit_value is None
        or remaining_balance is None
        or rate is None
        or amortization is None
        or target_dscr is None
        or target_dscr <= 0
        or max_ltv is None
        or not 0 <= max_ltv <= 1
    ):
        add_issue(
            issues,
            "cannot compute refi-ability because NOI, exit value, remaining balance, "
            "valid refinance thresholds, or debt terms are unavailable",
        )
        return None, detail
    constant = mortgage_constant(rate, amortization)
    if constant is None or constant <= 0:
        add_issue(issues, "cannot compute refi-ability because debt constant is unavailable")
        return None, detail
    dscr_capacity = noi / target_dscr / constant
    ltv_capacity = exit_value * max_ltv
    capacity = min(dscr_capacity, ltv_capacity)
    detail.update(
        {
            "dscr_debt_capacity": dscr_capacity,
            "ltv_debt_capacity": ltv_capacity,
            "maximum_refinance_proceeds": capacity,
        }
    )
    return remaining_balance <= capacity, detail


def _scenario(
    name: str,
    deal_inputs: dict[str, Any],
    raw_shocks: Mapping[str, Any],
    label: str,
    preset: bool,
) -> dict[str, Any]:
    issues: list[str] = []
    shock = _normalize_shocks(raw_shocks)
    noi, noi_bridge = _stressed_noi(deal_inputs, shock, issues)
    debt = debt_inputs(
        deal_inputs,
        rate_delta=float(shock["interest_rate_delta"] or 0.0),
        issues=issues,
    )
    annual_service = first_year_debt_service(debt)
    loan_amount = debt.get("loan_amount")
    if annual_service is None and loan_amount is not None and loan_amount > 0:
        add_issue(issues, "cannot compute DSCR because annual debt service is unavailable")
    scenario_dscr = dscr(noi, annual_service)
    if loan_amount == 0:
        add_issue(issues, "cannot compute DSCR because annual debt service is zero; no debt")
    elif annual_service == 0:
        add_issue(issues, "cannot compute DSCR because annual debt service is zero")
    elif noi is None:
        add_issue(issues, "cannot compute DSCR because stressed NOI is unavailable")

    price = debt.get("price")
    equity = None
    if price is not None and loan_amount is not None:
        equity = price - loan_amount
        if equity <= 0:
            add_issue(
                issues,
                "cannot compute cash-on-cash or equity returns because initial equity "
                "must be positive",
            )
            equity = None
    elif price is None:
        add_issue(issues, "cannot compute cash-on-cash or IRR because price is missing")
    scenario_coc = cash_on_cash(noi, annual_service, equity)

    hold_months = _effective_hold_months(deal_inputs, shock, issues)
    base_exit_cap = get_rate(deal_inputs, "exit_cap", "exit_cap_rate")
    exit_cap = (
        base_exit_cap + float(shock["exit_cap_delta"] or 0.0)
        if base_exit_cap is not None
        else None
    )
    if base_exit_cap is None:
        add_issue(issues, "cannot compute IRR because exit_cap is missing")
    elif exit_cap is not None and exit_cap <= 0:
        add_issue(issues, "cannot compute IRR because shocked exit_cap must be positive")
        exit_cap = None

    terminal_value = noi / exit_cap if noi is not None and exit_cap else None
    remaining_balance = (
        loan_balance(debt, hold_months) if hold_months is not None else None
    )
    annualized_irr = None
    scenario_equity_multiple = None
    cash_flows: list[float] | None = None
    if (
        equity is not None
        and noi is not None
        and hold_months is not None
        and terminal_value is not None
        and remaining_balance is not None
    ):
        cash_flows = [-equity]
        complete = True
        for month in range(1, hold_months + 1):
            service = monthly_debt_service(debt, month)
            if service is None:
                complete = False
                break
            flow = noi / 12 - service
            if month == hold_months:
                flow += terminal_value - remaining_balance
            cash_flows.append(flow)
        if complete:
            monthly_irr = levered_irr(cash_flows)
            if monthly_irr is not None and monthly_irr > -100:
                annualized_irr = ((1 + monthly_irr / 100) ** 12 - 1) * 100
            else:
                add_issue(
                    issues,
                    "cannot compute IRR because cash flows do not contain a solvable "
                    "negative-to-positive return pattern",
                )
            invested = equity + sum(-flow for flow in cash_flows[1:] if flow < 0)
            distributions = sum(flow for flow in cash_flows[1:] if flow > 0)
            scenario_equity_multiple = equity_multiple(distributions, invested)

    stressed_occupancy = noi_bridge.get("stressed_occupancy")
    stressed_gpr = get_number(
        deal_inputs, "gross_potential_rent", "gpr", "annual_gross_rent"
    )
    if stressed_gpr is not None:
        stressed_gpr *= 1 + float(shock["rent_delta"] or 0.0)
    stressed_opex = get_number(
        deal_inputs, "operating_expenses", "opex", "annual_operating_expenses"
    )
    if stressed_opex is not None:
        stressed_opex = (
            stressed_opex * (1 + float(shock["opex_delta"] or 0.0))
            + float(noi_bridge.get("management_fee_floor_expense", 0.0))
            + float(noi_bridge.get("replacement_reserves", 0.0))
        )
    break_even_occ = break_even_occupancy(stressed_opex, annual_service, stressed_gpr)
    break_even_flags = {
        "debt_service_covered": (
            noi >= annual_service
            if noi is not None and annual_service is not None and annual_service > 0
            else None
        ),
        "occupancy_above_break_even": (
            stressed_occupancy * 100 >= break_even_occ
            if stressed_occupancy is not None and break_even_occ is not None
            else None
        ),
        "exit_value_above_loan_balance": (
            terminal_value >= remaining_balance
            if terminal_value is not None and remaining_balance is not None
            else None
        ),
        "break_even_occupancy_percent": break_even_occ,
    }

    refi_flag, refi_detail = _refi_ability(
        deal_inputs,
        noi,
        terminal_value,
        remaining_balance,
        debt,
        issues,
    )
    assumptions = normalized_assumptions(deal_inputs)
    assumptions.update(
        {
            "scenario_name": name,
            "preset": preset,
            "preset_or_custom_label": label,
            "raw_shocks": dict(raw_shocks),
            "normalized_applied_shocks": shock,
            "noi_bridge": noi_bridge,
            "debt_terms": debt,
            "effective_hold_months": hold_months,
            "base_exit_cap": base_exit_cap,
            "stressed_exit_cap": exit_cap,
        }
    )
    return {
        "name": name,
        "honesty_label": label,
        "is_convention": True,
        "is_preset": preset,
        "shocks": dict(raw_shocks),
        "applied_shocks": shock,
        "noi": noi,
        "annual_debt_service": annual_service,
        "dscr": scenario_dscr,
        "cash_on_cash": scenario_coc,
        "irr": annualized_irr,
        "levered_irr": annualized_irr,
        "equity_multiple": scenario_equity_multiple,
        "exit_value": terminal_value,
        "remaining_loan_balance": remaining_balance,
        "refi_ability_flag": refi_flag,
        "refi_ability": refi_detail,
        "break_even_flags": break_even_flags,
        "cash_flows_monthly": cash_flows,
        "assumptions": assumptions,
        "not_computable": issues,
    }


def _scenario_specs(
    shocks: Mapping[str, Any] | Sequence[str] | str | None,
) -> list[tuple[str, dict[str, Any], str, bool]]:
    if shocks is None or shocks == "presets":
        return [
            (name, dict(spec["shocks"]), str(spec["label"]), True)
            for name, spec in SCENARIO_PRESETS.items()
        ]
    if isinstance(shocks, str):
        if shocks not in SCENARIO_PRESETS:
            raise ValueError(f"unknown scenario preset: {shocks}")
        spec = SCENARIO_PRESETS[shocks]
        return [(shocks, dict(spec["shocks"]), str(spec["label"]), True)]
    if isinstance(shocks, Sequence) and not isinstance(shocks, (str, bytes)):
        specs = []
        for name in shocks:
            if name not in SCENARIO_PRESETS:
                raise ValueError(f"unknown scenario preset: {name}")
            preset = SCENARIO_PRESETS[name]
            specs.append((name, dict(preset["shocks"]), str(preset["label"]), True))
        return specs
    if not isinstance(shocks, Mapping):
        raise TypeError("shocks must be a mapping, preset name, preset sequence, or None")
    if set(shocks).issubset(_SHOCK_KEYS):
        return [
            (
                "custom",
                dict(shocks),
                "CONVENTION: caller-supplied stress; not a prediction",
                False,
            )
        ]
    if all(isinstance(value, Mapping) for value in shocks.values()):
        return [
            (
                str(name),
                dict(value),
                "CONVENTION: caller-supplied stress; not a prediction",
                False,
            )
            for name, value in shocks.items()
        ]
    raise ValueError("scenario mapping must contain shock keys or named shock mappings")


def stress_test(
    deal_inputs: dict[str, Any],
    shocks: Mapping[str, Any] | Sequence[str] | str | None = None,
) -> dict[str, Any]:
    """Run one or more explicit stress cases against a single deal.

    ``shocks`` may be a shock mapping, a preset name, a sequence of preset names,
    a mapping of custom scenario names to shock mappings, or ``None`` for all four
    preset CONVENTIONS. Rent and opex shocks are relative changes; occupancy is a
    decimal percentage-point change; interest and exit-cap deltas accept decimal
    changes or explicit ``*_bps`` keys; ``hold_years`` changes years and
    ``sale_timing`` changes months.
    """
    if not isinstance(deal_inputs, dict):
        raise TypeError("deal_inputs must be a dict")
    specs = _scenario_specs(shocks)
    scenarios = {
        name: _scenario(name, deal_inputs, raw, label, preset)
        for name, raw, label, preset in specs
    }
    return {
        "honesty_label": HONESTY_LABEL,
        "assumptions": normalized_assumptions(deal_inputs),
        "scenario_order": [name for name, *_ in specs],
        "scenarios": scenarios,
    }
