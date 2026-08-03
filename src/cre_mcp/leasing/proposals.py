"""Transparent landlord-side comparison of structured lease proposals.

The credit and downtime scores in this module are comparison conventions, not
default probabilities, forecasts, or representations that a tenant will sign.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_DISCOUNT_RATE = 0.08

# Heuristic comparison weights only.  They are deliberately public and are not
# empirical probabilities of payment, renewal, or lease execution.
CREDIT_CONVENTION_WEIGHTS: dict[str, float] = {
    "corporate": 1.00,
    "franchisee_with_guaranty": 0.85,
    "franchisee_without_guaranty": 0.70,
    "local_with_guaranty": 0.60,
    "local_without_guaranty": 0.45,
    "unknown": 0.35,
}

DOWNTIME_CONTINGENCY_POINTS: dict[str, float] = {
    "zoning_or_use": 35.0,
    "permit": 30.0,
    "financing": 25.0,
    "franchise_approval": 25.0,
    "board_or_corporate_approval": 20.0,
    "construction_or_ti": 15.0,
    "inspection_or_diligence": 10.0,
    "other_unresolved": 8.0,
}

_CLOSED_CONTINGENCY_STATUSES = {
    "cleared",
    "complete",
    "completed",
    "resolved",
    "satisfied",
    "waived",
}


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return result


def _rate(value: Any, label: str) -> float:
    result = _number(value, label)
    if abs(result) > 1:
        result /= 100
    if result <= -1:
        raise ValueError(f"{label} must be greater than -100%")
    return result


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _text(value: Any, label: str) -> str:
    result = str(value).strip() if value is not None else ""
    if not result:
        raise ValueError(f"{label} is required")
    return result


def _term_months(term_years: Any, label: str) -> tuple[float, int]:
    years = _number(term_years, label)
    if years <= 0:
        raise ValueError(f"{label} must be greater than zero")
    raw_months = years * 12
    months = round(raw_months)
    if not math.isclose(raw_months, months, abs_tol=1e-8):
        raise ValueError(f"{label} must resolve to a whole number of months")
    return years, months


def _annual_compound_schedule(
    base_rent_psf: float, term_months: int, rate: float
) -> list[float]:
    return [base_rent_psf * (1 + rate) ** (month // 12) for month in range(term_months)]


def _apply_event(schedule: list[float], event: Mapping[str, Any], index: int) -> dict[str, Any]:
    if "month" in event:
        effective_month = int(_number(event["month"], f"escalations[{index}].month"))
    else:
        year = int(_number(event.get("year", index + 2), f"escalations[{index}].year"))
        effective_month = (year - 1) * 12 + 1
    if effective_month < 1:
        raise ValueError("escalation effective month must be at least 1")
    start = effective_month - 1
    if start >= len(schedule):
        return {"effective_month": effective_month, "ignored_beyond_term": True}

    if "rent_psf" in event:
        value = _number(event["rent_psf"], f"escalations[{index}].rent_psf", minimum=0)
        operation = "set_rent_psf"
        for month in range(start, len(schedule)):
            schedule[month] = value
    elif any(key in event for key in ("increase_psf", "step_psf", "amount_psf")):
        key = next(key for key in ("increase_psf", "step_psf", "amount_psf") if key in event)
        value = _number(event[key], f"escalations[{index}].{key}")
        operation = "add_psf"
        for month in range(start, len(schedule)):
            schedule[month] += value
            if schedule[month] < 0:
                raise ValueError("escalation cannot produce negative rent")
    else:
        key = next(
            (key for key in ("increase_pct", "rate", "pct", "annual_pct") if key in event),
            None,
        )
        if key is None:
            raise ValueError(
                "escalation event requires rent_psf, increase_psf, or increase_pct"
            )
        value = _rate(event[key], f"escalations[{index}].{key}")
        operation = "multiply"
        for month in range(start, len(schedule)):
            schedule[month] *= 1 + value
    return {"effective_month": effective_month, "operation": operation, "value": value}


def _rent_schedule(
    base_rent_psf: float, term_months: int, escalations: Any
) -> tuple[list[float], dict[str, Any]]:
    if escalations is None:
        return [base_rent_psf] * term_months, {
            "method": "none",
            "input": None,
            "events": [],
        }
    if isinstance(escalations, bool):
        raise ValueError("escalations must not be boolean")
    if isinstance(escalations, (int, float)):
        rate = _rate(escalations, "escalations")
        return _annual_compound_schedule(base_rent_psf, term_months, rate), {
            "method": "annual_compound_rate",
            "input": escalations,
            "normalized_rate": rate,
            "timing": "first increase at month 13, then each lease-year anniversary",
        }
    if isinstance(escalations, Mapping):
        if "schedule" in escalations:
            raw_events = escalations["schedule"]
        else:
            rate_key = next(
                (key for key in ("annual_rate", "annual_pct", "rate", "pct") if key in escalations),
                None,
            )
            if rate_key is not None:
                rate = _rate(escalations[rate_key], f"escalations.{rate_key}")
                return _annual_compound_schedule(base_rent_psf, term_months, rate), {
                    "method": "annual_compound_rate",
                    "input": dict(escalations),
                    "normalized_rate": rate,
                    "timing": "first increase at month 13, then each lease-year anniversary",
                }
            raw_events = [escalations]
    else:
        raw_events = escalations

    if isinstance(raw_events, (str, bytes)) or not isinstance(raw_events, Sequence):
        raise ValueError("escalations must be a rate, mapping, or sequence")
    schedule = [base_rent_psf] * term_months
    events: list[dict[str, Any]] = []
    for index, raw_event in enumerate(raw_events):
        if isinstance(raw_event, Mapping):
            event = dict(raw_event)
        else:
            event = {"year": index + 2, "increase_pct": raw_event}
        events.append(_apply_event(schedule, event, index))
    return schedule, {
        "method": "explicit_events",
        "input": list(raw_events),
        "events": events,
        "timing": "event year N begins at month (N-1)*12+1; month is one-based",
    }


def _credit(credit: Any) -> dict[str, Any]:
    if credit is None:
        value: Mapping[str, Any] = {}
    elif isinstance(credit, Mapping):
        value = credit
    else:
        raise ValueError("credit must be a mapping")
    credit_type = _slug(value.get("type", "unknown"))
    if credit_type == "franchise":
        credit_type = "franchisee"
    if credit_type not in {"corporate", "franchisee", "local", "unknown"}:
        raise ValueError("credit.type must be corporate, franchisee, local, or unknown")
    raw_guaranty = value.get("guaranty")
    if isinstance(raw_guaranty, str):
        guaranty = _slug(raw_guaranty) not in {"", "false", "no", "none", "absent"}
    else:
        guaranty = bool(raw_guaranty)
    key = credit_type if credit_type in {"corporate", "unknown"} else (
        f"{credit_type}_{'with' if guaranty else 'without'}_guaranty"
    )
    weight = CREDIT_CONVENTION_WEIGHTS[key]
    return {
        "type": credit_type,
        "guaranty": raw_guaranty,
        "guaranty_present": guaranty,
        "convention_key": key,
        "convention_weight": weight,
        "label": "structured caller input; not independently verified",
    }


def _contingencies(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return list(value)
    raise ValueError("contingencies must be text, a mapping, or a sequence")


def _contingency_kind(text: str) -> str:
    if any(word in text for word in ("zoning", "use approval", "entitlement")):
        return "zoning_or_use"
    if "permit" in text:
        return "permit"
    if any(word in text for word in ("finance", "financing", "loan")):
        return "financing"
    if "franchise" in text:
        return "franchise_approval"
    if any(word in text for word in ("board", "corporate approval", "committee")):
        return "board_or_corporate_approval"
    if any(word in text for word in ("construction", "buildout", "build-out", " ti ")):
        return "construction_or_ti"
    if any(word in text for word in ("inspection", "diligence", "due diligence")):
        return "inspection_or_diligence"
    return "other_unresolved"


def _downtime_risk(credit: Mapping[str, Any], contingencies: list[Any]) -> dict[str, Any]:
    credit_points = (1 - float(credit["convention_weight"])) * 100
    details: list[dict[str, Any]] = []
    contingency_points = 0.0
    for item in contingencies:
        if isinstance(item, Mapping):
            status = _slug(item.get("status", ""))
            text = " ".join(str(item.get(key, "")) for key in ("type", "name", "note")).strip()
        else:
            status = ""
            text = str(item).strip()
        resolved = status in _CLOSED_CONTINGENCY_STATUSES
        kind = _contingency_kind(f" {text.casefold()} ")
        points = 0.0 if resolved else DOWNTIME_CONTINGENCY_POINTS[kind]
        contingency_points += points
        details.append(
            {"input": item, "kind": kind, "resolved": resolved, "comparison_points": points}
        )
    total = credit_points + contingency_points
    notes = [
        "Lower comparison points rank ahead for the min-downtime objective.",
        "Points are screening conventions, not predicted vacancy days or execution probabilities.",
    ]
    if contingencies:
        notes.append("Unresolved contingencies can delay execution; confirm dates and responsibility in documents.")
    else:
        notes.append("No contingencies were supplied; absence from input is not proof that none exist.")
    return {
        "comparison_points": round(total, 4),
        "credit_points": round(credit_points, 4),
        "contingency_points": round(contingency_points, 4),
        "contingency_details": details,
        "notes": notes,
    }


def _ranking(rows: list[dict[str, Any]], objective: str) -> list[dict[str, Any]]:
    if objective == "max_npv":
        ordered = sorted(rows, key=lambda row: (-row["net_npv"], -row["credit_weight"], row["proposal_index"]))
        value_key = "net_npv"
    elif objective == "max_credit":
        ordered = sorted(rows, key=lambda row: (-row["credit_weight"], -row["net_npv"], row["proposal_index"]))
        value_key = "credit_weight"
    else:
        ordered = sorted(rows, key=lambda row: (row["downtime_risk"]["comparison_points"], -row["credit_weight"], -row["net_npv"], row["proposal_index"]))
        value_key = "downtime_comparison_points"
    result = []
    for rank, row in enumerate(ordered, 1):
        value = (
            row["downtime_risk"]["comparison_points"]
            if objective == "min_downtime"
            else row[value_key]
        )
        result.append(
            {
                "rank": rank,
                "proposal_index": row["proposal_index"],
                "proposal_id": row["proposal_id"],
                "tenant": row["tenant"],
                "objective_value": value,
                "objective_value_key": value_key,
            }
        )
    return result


def compare_lease_proposals(
    proposals: Sequence[Mapping[str, Any]],
    space: Mapping[str, Any],
    discount_rate: float | None = None,
) -> dict[str, Any]:
    """Compare proposal economics, input-labeled credit, and downtime framing.

    Rent is modeled monthly from a landlord perspective.  TI is paid at time
    zero; base rent arrives at each month end; free rent waives the first N
    months; and annual effective rent is undiscounted net collected base rent
    less TI, divided by square feet and lease years.
    """
    if isinstance(proposals, (str, bytes)) or not isinstance(proposals, Sequence) or not proposals:
        raise ValueError("proposals must be a non-empty sequence")
    if not isinstance(space, Mapping):
        raise ValueError("space must be a mapping")
    sf = _number(space.get("sf"), "space.sf")
    if sf <= 0:
        raise ValueError("space.sf must be greater than zero")
    annual_discount = _rate(
        DEFAULT_DISCOUNT_RATE if discount_rate is None else discount_rate,
        "discount_rate",
    )
    if annual_discount < 0:
        raise ValueError("discount_rate must be non-negative")
    monthly_discount = (1 + annual_discount) ** (1 / 12) - 1

    compared: list[dict[str, Any]] = []
    for index, raw in enumerate(proposals):
        if not isinstance(raw, Mapping):
            raise ValueError(f"proposals[{index}] must be a mapping")
        tenant = _text(raw.get("tenant"), f"proposals[{index}].tenant")
        proposal_id = str(raw.get("proposal_id") or tenant)
        rent_psf = _number(raw.get("rent_psf"), f"proposals[{index}].rent_psf")
        if rent_psf <= 0:
            raise ValueError(f"proposals[{index}].rent_psf must be greater than zero")
        years, months = _term_months(raw.get("term_years"), f"proposals[{index}].term_years")
        ti_psf = _number(raw.get("ti_psf", 0), f"proposals[{index}].ti_psf", minimum=0)
        free_months_value = _number(
            raw.get("free_rent_months", 0),
            f"proposals[{index}].free_rent_months",
            minimum=0,
        )
        free_months = round(free_months_value)
        if not math.isclose(free_months_value, free_months, abs_tol=1e-8):
            raise ValueError(f"proposals[{index}].free_rent_months must be a whole number")
        if free_months > months:
            raise ValueError(f"proposals[{index}].free_rent_months cannot exceed the lease term")

        schedule_psf, escalation_basis = _rent_schedule(rent_psf, months, raw.get("escalations"))
        gross_monthly = [annual_psf * sf / 12 for annual_psf in schedule_psf]
        collected_monthly = [0.0 if month < free_months else amount for month, amount in enumerate(gross_monthly)]
        ti_dollars = ti_psf * sf
        gross_total = sum(gross_monthly)
        collected_total = sum(collected_monthly)
        free_rent_dollars = gross_total - collected_total
        net_total = collected_total - ti_dollars
        gross_npv = sum(amount / ((1 + monthly_discount) ** month) for month, amount in enumerate(gross_monthly, 1))
        collected_npv = sum(amount / ((1 + monthly_discount) ** month) for month, amount in enumerate(collected_monthly, 1))
        net_npv = collected_npv - ti_dollars

        credit = _credit(raw.get("credit"))
        credit_weight = float(credit["convention_weight"])
        credit_adjusted_npv = net_npv * credit_weight
        low_npv = min(net_npv, credit_adjusted_npv)
        high_npv = max(net_npv, credit_adjusted_npv)
        contingencies = _contingencies(raw.get("contingencies"))
        downtime = _downtime_risk(credit, contingencies)
        gross_average_psf = gross_total / sf / years
        free_concession_psf = free_rent_dollars / sf / years
        ti_amortization_psf = ti_psf / years
        effective_psf = net_total / sf / years
        annualized_effective_rent = effective_psf

        monthly_cash_flows = [-ti_dollars, *collected_monthly]
        row = {
            "proposal_index": index,
            "proposal_id": proposal_id,
            "tenant": tenant,
            "rent_psf": rent_psf,
            "term_years": years,
            "term_months": months,
            "ti_psf": ti_psf,
            "ti_dollars": round(ti_dollars, 2),
            "free_rent_months": free_months,
            "free_rent_dollars": round(free_rent_dollars, 2),
            "gross_rent_total": round(gross_total, 2),
            "collected_rent_total": round(collected_total, 2),
            "net_undiscounted_cash_flow": round(net_total, 2),
            "gross_average_rent_psf": round(gross_average_psf, 6),
            "free_rent_concession_psf_per_year": round(free_concession_psf, 6),
            "ti_amortization_psf_per_year": round(ti_amortization_psf, 6),
            "effective_rent_psf": round(effective_psf, 6),
            "annualized_effective_rent": round(annualized_effective_rent, 6),
            "annualized_effective_rent_dollars": round(net_total / years, 2),
            "effective_rent": {
                "annual_psf": round(effective_psf, 6),
                "annual_dollars": round(net_total / years, 2),
                "formula": "(collected base rent - TI dollars) / term years / space SF",
                "bridge": {
                    "gross_average_rent_psf": round(gross_average_psf, 6),
                    "less_free_rent_psf_per_year": round(free_concession_psf, 6),
                    "less_ti_amortization_psf_per_year": round(ti_amortization_psf, 6),
                },
            },
            "gross_rent_npv": round(gross_npv, 2),
            "collected_rent_npv": round(collected_npv, 2),
            "net_npv": round(net_npv, 2),
            "npv": round(net_npv, 2),
            "credit_adjusted_npv": round(credit_adjusted_npv, 2),
            "npv_range": {
                "low": round(low_npv, 2),
                "high": round(high_npv, 2),
                "unweighted_economics": round(net_npv, 2),
                "credit_weighted_convention": round(credit_adjusted_npv, 2),
                "label": "framing range, not a probabilistic confidence interval",
            },
            "credit": credit,
            "credit_weight": credit_weight,
            "credit_framing": "Structured input plus exposed convention; not independently verified and not a default probability.",
            "contingencies": contingencies,
            "downtime_risk": downtime,
            "escalation_basis": escalation_basis,
            "cash_flows": {
                "monthly": [round(value, 2) for value in monthly_cash_flows],
                "month_zero_ti": round(-ti_dollars, 2),
                "monthly_collected_base_rent": [round(value, 2) for value in collected_monthly],
                "monthly_gross_base_rent": [round(value, 2) for value in gross_monthly],
            },
            "assumptions": {
                "perspective": "landlord",
                "rent_timing": "base rent received at each month end",
                "ti_timing": "full TI paid at time zero",
                "free_rent_timing": "first N lease months; base rent only",
                "discounting": "annual effective discount rate converted to an equivalent monthly rate",
                "annual_discount_rate": annual_discount,
                "monthly_discount_rate": monthly_discount,
                "recoveries_cam_and_percentage_rent": "excluded because not supplied",
                "renewals_terminal_value_and_downtime_cash_flow": "excluded",
                "currency": "nominal dollars; currency unit follows caller input",
            },
        }
        compared.append(row)

    rankings = {
        "max_npv": _ranking(compared, "max_npv"),
        "max_credit": _ranking(compared, "max_credit"),
        "min_downtime": _ranking(compared, "min_downtime"),
    }
    return {
        "space": {"sf": sf},
        "discount_rate": annual_discount,
        "monthly_discount_rate": monthly_discount,
        "proposals": compared,
        "rankings": rankings,
        "ranked_by_objective": rankings,
        "credit_convention_weights": dict(CREDIT_CONVENTION_WEIGHTS),
        "downtime_contingency_points": dict(DOWNTIME_CONTINGENCY_POINTS),
        "objective_note": "Objectives are ranked separately; this comparison does not select a single winner or assert that any tenant will sign.",
        "npv_range_note": "Each range spans exposed credit-weighted framing and unweighted net economics; it is not a probabilistic bound.",
        "global_assumptions": {
            "discount_rate_default": DEFAULT_DISCOUNT_RATE,
            "discount_rate_input": discount_rate,
            "discount_rate_normalization": "absolute values above 1 are treated as percentage points",
            "credit_weights": "screening convention only, not tenant-specific empirical probabilities",
            "downtime_points": "screening comparison points only, not estimated days",
        },
    }


__all__ = [
    "CREDIT_CONVENTION_WEIGHTS",
    "DEFAULT_DISCOUNT_RATE",
    "DOWNTIME_CONTINGENCY_POINTS",
    "compare_lease_proposals",
]
