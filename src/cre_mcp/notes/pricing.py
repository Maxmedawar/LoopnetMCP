"""Expected-path distressed-note pricing with visible conventions and counsel gates."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from cre_mcp.notes.timelines import COUNSEL_VERIFICATION_FLAG, estimate_timeline
from cre_mcp.notes.waterfall import coerce_range

RANGE_KEYS = ("low", "base", "high")
UNKNOWN_RANGE = {"low": "UNKNOWN", "base": "UNKNOWN", "high": "UNKNOWN"}
PATH_NAMES = (
    "reinstate",
    "modify",
    "foreclose_to_reo",
    "deed_in_lieu",
    "note_sale",
)
DEFAULT_PATH_PROBABILITIES = {
    "sub": {
        "reinstate": 0.30,
        "modify": 0.35,
        "foreclose_to_reo": 0.15,
        "deed_in_lieu": 0.10,
        "note_sale": 0.10,
    },
    "non": {
        "reinstate": 0.10,
        "modify": 0.20,
        "foreclose_to_reo": 0.40,
        "deed_in_lieu": 0.15,
        "note_sale": 0.15,
    },
}
PROBABILITY_CONVENTION_NOTE = (
    "Default path probabilities are uncalibrated screening CONVENTIONS, not forecasts, "
    "appraisals, credit opinions, or historical frequencies. Override all five with deal-specific "
    "probabilities after servicing, borrower, title, collateral, and counsel diligence."
)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _annual_rate(value: Any, label: str) -> float:
    rate = _number(value, label)
    if rate < 0:
        raise ValueError(f"{label} cannot be negative")
    if rate > 1:
        rate /= 100.0
    return rate


def _yield_range(value: Any) -> dict[str, float]:
    result = coerce_range(value, "target_yield_range")
    if result["high"] > 1:
        if result["low"] <= 1:
            raise ValueError("target_yield_range cannot mix decimal and percentage units")
        result = {key: amount / 100.0 for key, amount in result.items()}
    return result


def _clean(value: float) -> float:
    return round(max(0.0, value), 8)


def _payment(principal: float, annual_coupon: float, months: int) -> float:
    if months <= 0:
        raise ValueError("remaining_months must be positive")
    monthly_rate = annual_coupon / 12.0
    if monthly_rate == 0:
        return principal / months
    return principal * monthly_rate / (1.0 - (1.0 + monthly_rate) ** -months)


def _annuity_pv(
    monthly_payment: float,
    months: int,
    annual_yield: float,
    balloon_payment: float = 0.0,
) -> float:
    """PV monthly cash flows at annual nominal yield divided by twelve."""

    monthly_yield = annual_yield / 12.0
    if monthly_yield == 0:
        annuity = monthly_payment * months
        balloon = balloon_payment
    else:
        factor = (1.0 - (1.0 + monthly_yield) ** -months) / monthly_yield
        annuity = monthly_payment * factor
        balloon = balloon_payment / (1.0 + monthly_yield) ** months
    return annuity + balloon


def _discount(value: float, annual_yield: float, months: float) -> float:
    return value / (1.0 + annual_yield / 12.0) ** months


def _status(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "performing": "performing",
        "current": "performing",
        "sub": "sub",
        "subperforming": "sub",
        "sub_performing": "sub",
        "non": "non",
        "nonperforming": "non",
        "non_performing": "non",
        "npl": "non",
    }
    if normalized not in aliases:
        raise ValueError("payment_history.status must be performing, sub, or non")
    return aliases[normalized]


def _probabilities(
    status: str,
    override: Mapping[str, Any] | None,
) -> tuple[dict[str, float], str]:
    if override is None:
        return dict(DEFAULT_PATH_PROBABILITIES[status]), "uncalibrated_default_convention"
    missing = set(PATH_NAMES) - set(override)
    extra = set(override) - set(PATH_NAMES)
    if missing or extra:
        raise ValueError(
            f"path_probabilities requires exactly {list(PATH_NAMES)}; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    probabilities = {
        name: _number(override[name], f"path_probabilities.{name}") for name in PATH_NAMES
    }
    if any(value < 0 for value in probabilities.values()):
        raise ValueError("path probabilities cannot be negative")
    total = sum(probabilities.values())
    if math.isclose(total, 100.0, rel_tol=0, abs_tol=1e-8):
        probabilities = {name: value / 100.0 for name, value in probabilities.items()}
        total = 1.0
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-8):
        raise ValueError(f"path probabilities must sum to 1.0; got {total}")
    return probabilities, "caller_override"


def _cost_range(
    costs: Mapping[str, Any],
    key: str,
    default: Any,
) -> tuple[dict[str, float], str]:
    return (
        coerce_range(costs.get(key, default), f"costs.{key}"),
        "provided" if key in costs else "screening_default_convention",
    )


def _unknown_pricing_result(
    *,
    reason: str,
    status: str,
    probabilities: Mapping[str, float] | None,
    probability_source: str | None,
    timeline: Mapping[str, Any] | None,
    assumptions: list[dict[str, Any]],
    flags: list[str],
) -> dict:
    paths = []
    for name in PATH_NAMES:
        paths.append(
            {
                "path": name,
                "probability": probabilities[name] if probabilities else "UNKNOWN",
                "probability_source": probability_source or "UNKNOWN",
                "time_months": dict(UNKNOWN_RANGE),
                "gross_recovery": dict(UNKNOWN_RANGE),
                "cost": dict(UNKNOWN_RANGE),
                "net_recovery": dict(UNKNOWN_RANGE),
                "present_value": dict(UNKNOWN_RANGE),
                "expected_contribution": dict(UNKNOWN_RANGE),
                "professional_review_required": True,
            }
        )
    return {
        "status": "UNKNOWN",
        "reason": reason,
        "payment_status": status,
        "price": dict(UNKNOWN_RANGE),
        "price_range": dict(UNKNOWN_RANGE),
        "paths": paths,
        "path_table": paths,
        "probability_total": sum(probabilities.values()) if probabilities else "UNKNOWN",
        "probability_convention": PROBABILITY_CONVENTION_NOTE,
        "timeline": timeline or {"status": "UNKNOWN"},
        "assumption_sheet": assumptions,
        "professional_review_required": True,
        "professional_review_flags": flags,
    }


def price_note(
    upb: Any,
    rate: Any,
    payment_history: Mapping[str, Any],
    collateral_value_range: Any,
    state: str,
    lien_position: Any,
    costs: Mapping[str, Any] | None,
    target_yield_range: Any,
    *,
    path_probabilities: Mapping[str, Any] | None = None,
) -> dict:
    """Price a performing or distressed note under visible low/base/high paths.

    Required cash-flow detail (``remaining_months`` and optionally
    ``monthly_payment``/``balloon_payment``) may be supplied in ``payment_history``
    or ``costs``. If term is absent, price is explicitly ``UNKNOWN``.
    """

    principal = _number(upb, "upb")
    if principal <= 0:
        raise ValueError("upb must be positive")
    coupon = _annual_rate(rate, "rate")
    history = dict(payment_history)
    payment_status = _status(history.get("status"))
    months_delinquent = int(_number(history.get("months_delinquent", 0), "months_delinquent"))
    if months_delinquent < 0:
        raise ValueError("months_delinquent cannot be negative")
    position = int(_number(lien_position, "lien_position"))
    if position < 1:
        raise ValueError("lien_position must be at least 1")
    collateral = coerce_range(collateral_value_range, "collateral_value_range")
    yields = _yield_range(target_yield_range)
    cost_inputs = dict(costs or {})
    remaining_value = history.get("remaining_months", cost_inputs.get("remaining_months"))
    remaining_months = (
        int(_number(remaining_value, "remaining_months"))
        if remaining_value is not None
        else None
    )
    balloon = _number(
        history.get("balloon_payment", cost_inputs.get("balloon_payment", 0)) or 0,
        "balloon_payment",
    )
    monthly_payment_value = history.get("monthly_payment", cost_inputs.get("monthly_payment"))

    flags = [
        COUNSEL_VERIFICATION_FLAG,
        "This is an advisory price screen, not an appraisal, broker opinion, fairness opinion, payoff, bid, or investment recommendation.",
        "Counsel/title/servicing review must verify ownership and enforceability, assignments/allonges, lien priority, notices, borrower defenses, payment history, advances, and the live payoff before purchase.",
        "Tax, bankruptcy, licensing, debt-collection, consumer/commercial-purpose, and servicing rules can change recoveries and authority to act.",
    ]
    assumptions = [
        {"driver": "upb", "value": principal, "source": "provided_unverified"},
        {"driver": "coupon_rate", "value": coupon, "source": "provided_unverified"},
        {"driver": "payment_status", "value": payment_status, "source": "provided_unverified"},
        {"driver": "months_delinquent", "value": months_delinquent, "source": "provided_unverified"},
        {"driver": "remaining_months", "value": remaining_months, "source": "provided_unverified" if remaining_value is not None else "unknown"},
        {"driver": "collateral_value_range", "value": collateral, "source": "provided_unverified"},
        {"driver": "state", "value": state, "source": "provided_unverified"},
        {"driver": "lien_position", "value": position, "source": "provided_unverified"},
        {"driver": "target_yield_range", "value": yields, "source": "provided"},
    ]

    if remaining_months is None or remaining_months <= 0:
        probabilities = probability_source = None
        if payment_status != "performing":
            override = path_probabilities or history.get("path_probabilities") or cost_inputs.get("path_probabilities")
            probabilities, probability_source = _probabilities(payment_status, override)
        flags.append("Remaining contractual term is missing; no maturity or cash-flow stream was guessed.")
        return _unknown_pricing_result(
            reason="remaining_months is required to price contractual reinstate/modify cash flows",
            status=payment_status,
            probabilities=probabilities,
            probability_source=probability_source,
            timeline=None,
            assumptions=assumptions,
            flags=flags,
        )

    if monthly_payment_value is None:
        monthly_payment = _payment(principal, coupon, remaining_months)
        payment_source = "derived_fully_amortizing_convention"
        flags.append(
            "Monthly payment was derived as fully amortizing over remaining_months; override it for IO, balloon, irregular, deferred, or modified cash flows."
        )
    else:
        monthly_payment = _number(monthly_payment_value, "monthly_payment")
        if monthly_payment < 0:
            raise ValueError("monthly_payment cannot be negative")
        payment_source = "provided_unverified"
    assumptions.extend(
        [
            {"driver": "monthly_payment", "value": monthly_payment, "source": payment_source},
            {"driver": "balloon_payment", "value": balloon, "source": "provided_unverified" if balloon else "default_zero"},
        ]
    )

    if payment_status == "performing":
        prices = {
            "low": _annuity_pv(monthly_payment, remaining_months, yields["high"], balloon),
            "base": _annuity_pv(monthly_payment, remaining_months, yields["base"], balloon),
            "high": _annuity_pv(monthly_payment, remaining_months, yields["low"], balloon),
        }
        prices = {key: _clean(value) for key, value in prices.items()}
        path = {
            "path": "performing_hold",
            "probability": 1.0,
            "probability_source": "deterministic_performing_cash_flow",
            "time_months": {
                "low": float(remaining_months),
                "base": float(remaining_months),
                "high": float(remaining_months),
            },
            "gross_recovery": prices,
            "cost": {"low": 0.0, "base": 0.0, "high": 0.0},
            "net_recovery": prices,
            "present_value": prices,
            "expected_contribution": prices,
            "professional_review_required": True,
        }
        return {
            "status": "MODELED_RANGE",
            "payment_status": "performing",
            "price": prices,
            "price_range": prices,
            "paths": [path],
            "path_table": [path],
            "probability_total": 1.0,
            "probability_convention": "Performing hold path is deterministic; borrower default risk is not separately probability-modeled.",
            "annuity_method": "monthly cash-flow PV at annual nominal target yield / 12",
            "timeline": {"status": "NOT_APPLICABLE_TO_CURRENT_CONTRACTUAL_CASH_FLOW"},
            "assumption_sheet": assumptions,
            "professional_review_required": True,
            "professional_review_flags": flags,
        }

    override = (
        path_probabilities
        or history.get("path_probabilities")
        or cost_inputs.get("path_probabilities")
    )
    probabilities, probability_source = _probabilities(payment_status, override)
    timeline = estimate_timeline(
        state,
        contested=bool(cost_inputs.get("contested", False)),
        bankruptcy_risk=cost_inputs.get("bankruptcy_risk"),
    )
    if timeline["status"] == "UNKNOWN":
        flags.extend(timeline["professional_review_flags"])
        return _unknown_pricing_result(
            reason="state foreclosure timeline is UNKNOWN; no substitute state was guessed",
            status=payment_status,
            probabilities=probabilities,
            probability_source=probability_source,
            timeline=timeline,
            assumptions=assumptions,
            flags=flags,
        )
    if position > 1 and "senior_liens" not in cost_inputs and "senior_liens_balance" not in cost_inputs:
        flags.append("Junior lien position was provided without senior payoff amounts; zero senior debt was not assumed.")
        return _unknown_pricing_result(
            reason="senior_liens or senior_liens_balance is required when lien_position > 1",
            status=payment_status,
            probabilities=probabilities,
            probability_source=probability_source,
            timeline=timeline,
            assumptions=assumptions,
            flags=flags,
        )

    marketing_discount, marketing_source = _cost_range(
        cost_inputs,
        "marketing_discount",
        {"low": 0.08, "base": 0.12, "high": 0.18},
    )
    if marketing_discount["high"] > 1:
        if marketing_discount["low"] <= 1:
            raise ValueError("costs.marketing_discount cannot mix decimal and percentage units")
        marketing_discount = {key: value / 100.0 for key, value in marketing_discount.items()}
    if marketing_discount["high"] > 1:
        raise ValueError("costs.marketing_discount cannot exceed 100%")
    foreclosure_cost, foreclosure_source = _cost_range(
        cost_inputs,
        "foreclosure",
        {"low": principal * 0.025, "base": principal * 0.04, "high": principal * 0.07},
    )
    legal_cost, legal_source = _cost_range(
        cost_inputs,
        "legal",
        {"low": principal * 0.01, "base": principal * 0.025, "high": principal * 0.05},
    )
    carry_monthly, carry_source = _cost_range(
        cost_inputs,
        "carry_monthly",
        {"low": principal * 0.001, "base": principal * 0.002, "high": principal * 0.004},
    )
    delinquency_reserve, delinquency_source = _cost_range(
        cost_inputs,
        "delinquency_reserve_monthly",
        {"low": principal * 0.0005, "base": principal * 0.001, "high": principal * 0.002},
    )
    reinstate_cost, reinstate_source = _cost_range(
        cost_inputs,
        "reinstate_cost",
        {"low": principal * 0.0025, "base": principal * 0.005, "high": principal * 0.01},
    )
    modify_cost, modify_source = _cost_range(
        cost_inputs,
        "modify_cost",
        {"low": principal * 0.005, "base": principal * 0.01, "high": principal * 0.02},
    )
    dil_cost, dil_source = _cost_range(
        cost_inputs,
        "dil_cost",
        {"low": principal * 0.0075, "base": principal * 0.015, "high": principal * 0.03},
    )
    note_sale_cost, note_sale_cost_source = _cost_range(
        cost_inputs,
        "note_sale_cost",
        {"low": principal * 0.005, "base": principal * 0.01, "high": principal * 0.02},
    )
    note_sale_factor, note_sale_factor_source = _cost_range(
        cost_inputs,
        "note_sale_recovery_factor",
        (
            {"low": 0.60, "base": 0.72, "high": 0.82}
            if payment_status == "sub"
            else {"low": 0.45, "base": 0.58, "high": 0.70}
        ),
    )
    reo_marketing_months, reo_months_source = _cost_range(
        cost_inputs,
        "reo_marketing_months",
        {"low": 2.0, "base": 4.0, "high": 8.0},
    )
    senior_key = "senior_liens" if "senior_liens" in cost_inputs else "senior_liens_balance"
    senior_liens = coerce_range(cost_inputs.get(senior_key, 0), f"costs.{senior_key}")
    property_tax_liens = coerce_range(
        cost_inputs.get("property_tax_liens", 0),
        "costs.property_tax_liens",
    )
    priority_claims = {
        key: senior_liens[key] + property_tax_liens[key] for key in RANGE_KEYS
    }

    assumptions.extend(
        [
            {"driver": "path_probabilities", "value": probabilities, "source": probability_source},
            {"driver": "marketing_discount", "value": marketing_discount, "source": marketing_source},
            {"driver": "foreclosure_cost", "value": foreclosure_cost, "source": foreclosure_source},
            {"driver": "legal_cost", "value": legal_cost, "source": legal_source},
            {"driver": "carry_monthly", "value": carry_monthly, "source": carry_source},
            {"driver": "delinquency_reserve_monthly", "value": delinquency_reserve, "source": delinquency_source},
            {"driver": "senior_liens", "value": senior_liens, "source": "provided_unverified" if senior_key in cost_inputs else "default_zero_first_lien_convention"},
            {"driver": "property_tax_liens", "value": property_tax_liens, "source": "provided_unverified" if "property_tax_liens" in cost_inputs else "default_zero_requires_tax_search"},
            {"driver": "note_sale_recovery_factor", "value": note_sale_factor, "source": note_sale_factor_source},
            {"driver": "reo_marketing_months", "value": reo_marketing_months, "source": reo_months_source},
        ]
    )
    flags.extend(timeline["professional_review_flags"])
    flags.extend(
        [
            PROBABILITY_CONVENTION_NOTE,
            "Property taxes were modeled ahead of mortgage debt; HOA super-priority, mechanics liens, IRS liens/redemption, judgments, and recording/subordination issues remain counsel/title questions.",
            "Default cost bands and note-sale recovery factors are stated screening conventions wherever the caller did not provide a value.",
            "The delinquency reserve is a pricing uncertainty/advance convention, not an assertion that the amount is legally recoverable from the borrower.",
        ]
    )

    total_possession = timeline["total_to_possession_months"]
    times = {
        "reinstate": {
            key: max(1.0, total_possession[key] * factor)
            for key, factor in zip(RANGE_KEYS, (0.08, 0.12, 0.18), strict=True)
        },
        "modify": {
            key: max(2.0, total_possession[key] * factor)
            for key, factor in zip(RANGE_KEYS, (0.15, 0.25, 0.35), strict=True)
        },
        "foreclose_to_reo": {
            key: total_possession[key] + reo_marketing_months[key] for key in RANGE_KEYS
        },
        "deed_in_lieu": {
            key: max(1.5, total_possession[key] * factor)
            for key, factor in zip(RANGE_KEYS, (0.10, 0.20, 0.30), strict=True)
        },
        "note_sale": {
            key: max(0.5, total_possession[key] * factor)
            for key, factor in zip(RANGE_KEYS, (0.04, 0.07, 0.10), strict=True)
        },
    }
    modified_rate = _annual_rate(cost_inputs.get("modified_rate", coupon), "costs.modified_rate")
    modified_term = int(
        _number(cost_inputs.get("modified_term_months", remaining_months), "costs.modified_term_months")
    )
    modification_factor, modification_factor_source = _cost_range(
        cost_inputs,
        "modification_principal_factor",
        {"low": 0.90, "base": 0.95, "high": 1.00},
    )
    assumptions.extend(
        [
            {"driver": "modified_rate", "value": modified_rate, "source": "provided_unverified" if "modified_rate" in cost_inputs else "current_coupon_convention"},
            {"driver": "modified_term_months", "value": modified_term, "source": "provided_unverified" if "modified_term_months" in cost_inputs else "remaining_term_convention"},
            {"driver": "modification_principal_factor", "value": modification_factor, "source": modification_factor_source},
            {"driver": "reinstate_cost", "value": reinstate_cost, "source": reinstate_source},
            {"driver": "modify_cost", "value": modify_cost, "source": modify_source},
            {"driver": "dil_cost", "value": dil_cost, "source": dil_source},
            {"driver": "note_sale_cost", "value": note_sale_cost, "source": note_sale_cost_source},
        ]
    )

    selector = {
        "low": {"economic": "low", "adverse": "high", "yield": "high", "time": "high"},
        "base": {"economic": "base", "adverse": "base", "yield": "base", "time": "base"},
        "high": {"economic": "high", "adverse": "low", "yield": "low", "time": "low"},
    }
    path_rows: list[dict[str, Any]] = []
    for path_name in PATH_NAMES:
        gross_values: dict[str, float] = {}
        cost_values: dict[str, float] = {}
        net_values: dict[str, float] = {}
        pv_values: dict[str, float] = {}
        expected_values: dict[str, float] = {}
        for scenario, keys in selector.items():
            economic_key = keys["economic"]
            adverse_key = keys["adverse"]
            yield_key = keys["yield"]
            time_key = keys["time"]
            path_time = times[path_name][time_key]
            annual_yield = yields[yield_key]
            carry = carry_monthly[adverse_key] * path_time
            past_due_reserve = delinquency_reserve[adverse_key] * months_delinquent
            collateral_after_discount_and_priority = max(
                0.0,
                collateral[economic_key] * (1.0 - marketing_discount[adverse_key])
                - priority_claims[adverse_key],
            )

            if path_name == "reinstate":
                gross = _annuity_pv(
                    monthly_payment,
                    remaining_months,
                    annual_yield,
                    balloon,
                )
                path_cost = reinstate_cost[adverse_key] + carry + past_due_reserve
            elif path_name == "modify":
                modified_principal = principal * modification_factor[economic_key]
                modified_payment = _payment(modified_principal, modified_rate, modified_term)
                gross = _annuity_pv(
                    modified_payment,
                    modified_term,
                    annual_yield,
                    0.0,
                )
                path_cost = modify_cost[adverse_key] + carry + past_due_reserve
            elif path_name == "foreclose_to_reo":
                gross = min(principal, collateral_after_discount_and_priority)
                path_cost = (
                    foreclosure_cost[adverse_key]
                    + legal_cost[adverse_key]
                    + carry
                    + past_due_reserve
                )
            elif path_name == "deed_in_lieu":
                gross = min(principal, collateral_after_discount_and_priority)
                path_cost = (
                    dil_cost[adverse_key]
                    + legal_cost[adverse_key] * 0.35
                    + carry
                    + past_due_reserve
                )
            else:
                gross = (
                    min(principal, collateral_after_discount_and_priority)
                    * note_sale_factor[economic_key]
                )
                path_cost = note_sale_cost[adverse_key] + carry + past_due_reserve

            net = max(0.0, gross - path_cost)
            pv = _discount(net, annual_yield, path_time)
            gross_values[scenario] = _clean(gross)
            cost_values[scenario] = _clean(path_cost)
            net_values[scenario] = _clean(net)
            pv_values[scenario] = _clean(pv)
            expected_values[scenario] = _clean(pv * probabilities[path_name])

        path_rows.append(
            {
                "path": path_name,
                "probability": probabilities[path_name],
                "probability_source": probability_source,
                "time_months": {key: round(times[path_name][key], 4) for key in RANGE_KEYS},
                "timeline_basis": (
                    "Foreclosure-to-REO uses the state total-to-possession band plus REO marketing; "
                    "consensual/note-sale times are disclosed fractions of that state band."
                ),
                "gross_recovery": gross_values,
                "cost": cost_values,
                "net_recovery": net_values,
                "present_value": pv_values,
                "expected_contribution": expected_values,
                "professional_review_required": True,
            }
        )

    prices = {
        scenario: _clean(sum(row["expected_contribution"][scenario] for row in path_rows))
        for scenario in RANGE_KEYS
    }
    return {
        "status": "MODELED_RANGE",
        "payment_status": payment_status,
        "price": prices,
        "price_range": prices,
        "paths": path_rows,
        "path_table": path_rows,
        "probability_total": round(sum(probabilities.values()), 10),
        "probability_source": probability_source,
        "probability_convention": PROBABILITY_CONVENTION_NOTE,
        "scenario_convention": (
            "low price uses low collateral, high discount/cost/yield, and long timing; "
            "high price reverses those assumptions."
        ),
        "timeline": timeline,
        "assumption_sheet": assumptions,
        "professional_review_required": True,
        "professional_review_flags": flags,
    }


__all__ = [
    "DEFAULT_PATH_PROBABILITIES",
    "PATH_NAMES",
    "PROBABILITY_CONVENTION_NOTE",
    "price_note",
]
