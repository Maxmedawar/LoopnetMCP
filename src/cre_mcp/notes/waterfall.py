"""Exact scenario-by-scenario lien recovery waterfall with unresolved priority flags."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.notes.timelines import COUNSEL_VERIFICATION_FLAG

RANGE_KEYS = ("low", "base", "high")
UNKNOWN_RANGE = {"low": "UNKNOWN", "base": "UNKNOWN", "high": "UNKNOWN"}
SUPPORTED_LIEN_TYPES = {
    "property_tax",
    "senior_mortgage",
    "junior",
    "hoa",
    "mechanics",
    "judgment",
    "irs",
}
PRIORITY_CONVENTION = (
    "Property-tax liens are modeled ahead of every other listed lien. Every non-tax lien follows "
    "the caller's asserted order; recording dates, subordination/intercreditor agreements, future "
    "advances, purchase-money rules, mechanics-lien relation-back, judgments, and federal liens "
    "are not adjudicated by this calculator."
)
HOA_PRIORITY_FLAG = (
    "HOA/condominium super-priority is jurisdiction-dependent and is FLAGGED, not assumed; counsel "
    "must determine the amount, perfection, notices, and priority."
)
IRS_REDEMPTION_NOTE = (
    "If a federal tax lien is affected by a nonjudicial sale, review 26 U.S.C. §§ 7425 and 7425(d): "
    "the United States may have a 120-day post-sale redemption right (or longer if state law allows). "
    "Notice, discharge, and redemption consequences require federal-tax/title counsel."
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


def coerce_range(
    value: Any,
    label: str,
    *,
    allow_negative: bool = False,
) -> dict[str, float]:
    """Convert a scalar, 2-item band, 3-item band, or range mapping to low/base/high."""

    if isinstance(value, Mapping):
        if "low" not in value or "high" not in value:
            raise ValueError(f"{label} range requires low and high")
        low = _number(value["low"], f"{label}.low")
        high = _number(value["high"], f"{label}.high")
        base = _number(value.get("base", (low + high) / 2.0), f"{label}.base")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) == 2:
            low = _number(value[0], f"{label}[0]")
            high = _number(value[1], f"{label}[1]")
            base = (low + high) / 2.0
        elif len(value) == 3:
            low = _number(value[0], f"{label}[0]")
            base = _number(value[1], f"{label}[1]")
            high = _number(value[2], f"{label}[2]")
        else:
            raise ValueError(f"{label} sequence requires 2 or 3 values")
    else:
        low = base = high = _number(value, label)
    if low > base or base > high:
        raise ValueError(f"{label} must satisfy low <= base <= high")
    if not allow_negative and low < 0:
        raise ValueError(f"{label} cannot be negative")
    return {"low": low, "base": base, "high": high}


def _discount_range(value: Any) -> dict[str, float]:
    result = coerce_range(value, "marketing_discount")
    if result["high"] > 1:
        if result["high"] > 100:
            raise ValueError("marketing_discount cannot exceed 100%")
        result = {key: amount / 100.0 for key, amount in result.items()}
    if result["high"] > 1:
        raise ValueError("marketing_discount cannot exceed 100%")
    return result


def _clean(value: float) -> float:
    return round(value, 8)


def _scenario_range(values: Mapping[str, float]) -> dict[str, float]:
    return {key: _clean(values[key]) for key in RANGE_KEYS}


def lien_recovery_waterfall(
    collateral_value_range: Any,
    marketing_discount: Any,
    liens: Sequence[Mapping[str, Any]],
    costs: Mapping[str, Any] | None,
) -> dict:
    """Apply an exact recovery pool to property tax first, then caller-ordered liens.

    Downside (``low`` recovery) uses low collateral, high discount, high expenses,
    high carry duration, and high accrued lien claims. Upside reverses those choices.
    ``per_diem`` accrues for 30 days per modeled carry month; this is an explicit
    day-count convention, not a payoff quote.
    """

    collateral = coerce_range(collateral_value_range, "collateral_value_range")
    discount = _discount_range(marketing_discount)
    cost_inputs = dict(costs or {})
    foreclosure = coerce_range(cost_inputs.get("foreclosure", 0), "costs.foreclosure")
    legal = coerce_range(cost_inputs.get("legal", 0), "costs.legal")
    carry_monthly = coerce_range(cost_inputs.get("carry_monthly", 0), "costs.carry_monthly")
    months = coerce_range(cost_inputs.get("months", 0), "costs.months")

    prepared: list[dict[str, Any]] = []
    for index, raw in enumerate(liens):
        lien = dict(raw)
        lien_type = str(lien.get("type", "")).strip().lower()
        if lien_type not in SUPPORTED_LIEN_TYPES:
            raise ValueError(
                f"liens[{index}].type must be one of {sorted(SUPPORTED_LIEN_TYPES)}"
            )
        holder = str(lien.get("holder", "")).strip()
        if not holder:
            raise ValueError(f"liens[{index}].holder is required")
        balance = coerce_range(lien.get("balance"), f"liens[{index}].balance")
        per_diem = _number(lien.get("per_diem", 0) or 0, f"liens[{index}].per_diem")
        if per_diem < 0:
            raise ValueError(f"liens[{index}].per_diem cannot be negative")
        prepared.append(
            {
                "input_position": index + 1,
                "holder": holder,
                "type": lien_type,
                "balance": balance,
                "per_diem": per_diem,
            }
        )

    property_tax = [lien for lien in prepared if lien["type"] == "property_tax"]
    other_liens = [lien for lien in prepared if lien["type"] != "property_tax"]
    ordered = [*property_tax, *other_liens]

    flags = [
        COUNSEL_VERIFICATION_FLAG,
        PRIORITY_CONVENTION,
        "Sale/foreclosure/legal/carry costs are deducted from collateral proceeds before liens as a screening convention; counsel and the closing statement must confirm charge priority.",
        "Obtain dated payoff statements; balances and per-diem accruals here are assumptions, not demands or title evidence.",
    ]
    if any(lien["type"] == "hoa" for lien in ordered):
        flags.append(HOA_PRIORITY_FLAG)
    if any(lien["type"] == "irs" for lien in ordered):
        flags.append(IRS_REDEMPTION_NOTE)
    if any(lien["type"] in {"mechanics", "judgment"} for lien in ordered):
        flags.append(
            "Mechanics/judgment priority is unresolved: confirm recording, attachment, relation-back, perfection, releases, homestead/entity facts, and state law."
        )
    if len(property_tax) > 1:
        flags.append(
            "Multiple property-tax claims were kept in caller order; taxing-unit parity and allocation require a title/payoff review."
        )
    if [lien["input_position"] for lien in ordered] != list(range(1, len(ordered) + 1)):
        flags.append(
            "At least one property-tax lien was moved ahead of the input order under the stated tax-priority convention."
        )

    scenario_inputs = {
        "low": {
            "collateral_key": "low",
            "discount_key": "high",
            "expense_key": "high",
            "claim_key": "high",
        },
        "base": {
            "collateral_key": "base",
            "discount_key": "base",
            "expense_key": "base",
            "claim_key": "base",
        },
        "high": {
            "collateral_key": "high",
            "discount_key": "low",
            "expense_key": "low",
            "claim_key": "low",
        },
    }
    recoveries: dict[int, dict[str, float]] = {
        id(lien): {} for lien in ordered
    }
    scenario_claims: dict[int, dict[str, float]] = {
        id(lien): {} for lien in ordered
    }
    shortfalls: dict[int, dict[str, float]] = {
        id(lien): {} for lien in ordered
    }
    gross_sale_proceeds: dict[str, float] = {}
    disposition_costs: dict[str, float] = {}
    net_pools: dict[str, float] = {}
    equity_remainder: dict[str, float] = {}

    for scenario, selectors in scenario_inputs.items():
        collateral_key = selectors["collateral_key"]
        discount_key = selectors["discount_key"]
        expense_key = selectors["expense_key"]
        claim_key = selectors["claim_key"]
        gross = collateral[collateral_key] * (1.0 - discount[discount_key])
        expenses = (
            foreclosure[expense_key]
            + legal[expense_key]
            + carry_monthly[expense_key] * months[expense_key]
        )
        pool = max(0.0, gross - expenses)
        gross_sale_proceeds[scenario] = gross
        disposition_costs[scenario] = expenses
        net_pools[scenario] = pool

        remaining = pool
        for lien in ordered:
            claim = lien["balance"][claim_key] + (
                lien["per_diem"] * 30.0 * months[claim_key]
            )
            recovered = min(claim, remaining)
            remaining = max(0.0, remaining - recovered)
            scenario_claims[id(lien)][scenario] = claim
            recoveries[id(lien)][scenario] = recovered
            shortfalls[id(lien)][scenario] = max(0.0, claim - recovered)
        equity_remainder[scenario] = remaining

    rows: list[dict[str, Any]] = []
    for effective_position, lien in enumerate(ordered, start=1):
        ordinary_claim = {
            key: lien["balance"][key] + lien["per_diem"] * 30.0 * months[key]
            for key in RANGE_KEYS
        }
        priority_note = (
            "Modeled as super-priority property tax."
            if lien["type"] == "property_tax"
            else "Priority is caller-asserted after property tax and requires counsel/title confirmation."
        )
        if lien["type"] == "hoa":
            priority_note += " HOA super-priority was not assumed."
        rows.append(
            {
                "holder": lien["holder"],
                "type": lien["type"],
                "input_position": lien["input_position"],
                "effective_position": effective_position,
                "stated_balance": lien["balance"],
                "per_diem": lien["per_diem"],
                "per_diem_day_count_convention": "30 days per modeled month",
                "claim": _scenario_range(ordinary_claim),
                "scenario_claim": _scenario_range(scenario_claims[id(lien)]),
                "recovery": _scenario_range(recoveries[id(lien)]),
                "shortfall": _scenario_range(shortfalls[id(lien)]),
                "priority_note": priority_note,
                "professional_review_required": True,
            }
        )

    assumptions = [
        {"driver": "collateral_value_range", "value": collateral, "source": "provided"},
        {"driver": "marketing_discount", "value": discount, "source": "provided"},
        {"driver": "foreclosure_cost", "value": foreclosure, "source": "provided" if "foreclosure" in cost_inputs else "default_zero"},
        {"driver": "legal_cost", "value": legal, "source": "provided" if "legal" in cost_inputs else "default_zero"},
        {"driver": "carry_monthly", "value": carry_monthly, "source": "provided" if "carry_monthly" in cost_inputs else "default_zero"},
        {"driver": "carry_months", "value": months, "source": "provided" if "months" in cost_inputs else "default_zero"},
        {"driver": "non_tax_priority", "value": "caller asserted order", "source": "convention_requires_counsel"},
    ]
    result = {
        "status": "MODELED_RANGE",
        "scenario_convention": (
            "low = recovery downside; base = midpoint inputs; high = recovery upside. "
            "Scenario claims may therefore run high/base/low across those recovery columns."
        ),
        "collateral_value": collateral,
        "marketing_discount": discount,
        "gross_sale_proceeds": _scenario_range(gross_sale_proceeds),
        "disposition_costs": _scenario_range(disposition_costs),
        "net_recovery_pool": _scenario_range(net_pools),
        "recovery_by_lien": rows,
        "recoveries": rows,
        "equity_remainder": _scenario_range(equity_remainder),
        "priority_convention": PRIORITY_CONVENTION,
        "hoa_super_lien_note": HOA_PRIORITY_FLAG,
        "irs_redemption_note": IRS_REDEMPTION_NOTE,
        "assumption_sheet": assumptions,
        "professional_review_required": True,
        "professional_review_flags": flags,
    }
    return result


__all__ = [
    "HOA_PRIORITY_FLAG",
    "IRS_REDEMPTION_NOTE",
    "PRIORITY_CONVENTION",
    "SUPPORTED_LIEN_TYPES",
    "coerce_range",
    "lien_recovery_waterfall",
]
