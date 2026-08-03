"""Value-engineering and percent-complete control calculations.

All money is integer cents.  Percent-complete views remain separate because an
invoice supports a billing calculation, a field inspection supports observed
work, and a schedule supports timing progress; none proves either of the other
two.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


DIVERGENCE_THRESHOLD_PCT_POINTS = 10.0
DIVERGENCE_CONVENTION = {
    "threshold_pct_points": DIVERGENCE_THRESHOLD_PCT_POINTS,
    "label": "control convention; not a contractual threshold",
}


def _cents(value: Any, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer number of cents")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _optional_cents(value: Any, field: str) -> int | None:
    return None if value is None else _cents(value, field)


def _rate(value: Any, field: str) -> tuple[Decimal, str]:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} must be a positive decimal or percent")
    raw = str(value).strip()
    is_percent = raw.endswith("%")
    if is_percent:
        raw = raw[:-1].strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a positive decimal or percent") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a positive decimal or percent")
    if is_percent or number > 1:
        if number > 100:
            raise ValueError(f"{field} cannot exceed 100%")
        return number / Decimal(100), "percent normalized to decimal"
    if number > 1:
        raise ValueError(f"{field} cannot exceed 100%")
    return number, "decimal rate"


def _pct(value: Any, field: str) -> tuple[Decimal, str]:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} must be between 0 and 100 percent")
    raw = str(value).strip()
    percent_string = raw.endswith("%")
    if percent_string:
        raw = raw[:-1].strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be between 0 and 100 percent") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be between 0 and 100 percent")
    if not percent_string and number <= 1:
        number *= Decimal(100)
        interpretation = "decimal fraction normalized to percent"
    else:
        interpretation = "percent"
    if number > 100:
        raise ValueError(f"{field} must be between 0 and 100 percent")
    return number, interpretation


def _money_divide(amount_cents: int, rate: Decimal) -> int:
    return int(
        (Decimal(amount_cents) / rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _pct_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _professional_flags() -> dict[str, bool]:
    return {
        "gc_review_required": True,
        "architect_review_required": True,
        "engineer_review_required": True,
        "inspector_review_required": True,
    }


def ve_option(
    option: Mapping[str, Any] | None,
    exit_cap: float | str | Decimal | None = None,
) -> dict[str, Any]:
    """Compare a VE option's capital change with its income-value effect.

    Sign convention: positive ``capex_delta_cents`` is additional spending and
    negative is savings.  Positive ``noi_delta_cents`` increases annual NOI.
    The income value effect is NOI delta divided by the stated exit cap.
    """

    try:
        if not isinstance(option, Mapping):
            raise ValueError("option must be an object")
        desc_raw = option.get("desc")
        if not isinstance(desc_raw, str) or not desc_raw.strip():
            raise ValueError("option.desc is required")
        desc = desc_raw.strip()
        capex_delta = _cents(option.get("capex_delta_cents"), "option.capex_delta_cents")
        noi_delta = _optional_cents(option.get("noi_delta_cents"), "option.noi_delta_cents")
        life_effect = option.get("life_effect")

        rate: Decimal | None = None
        rate_interpretation: str | None = None
        if exit_cap is not None:
            rate, rate_interpretation = _rate(exit_cap, "exit_cap")

        capex_value_effect = -capex_delta
        if noi_delta is None:
            noi_value_delta = None
            net_value_delta = None
            completeness = "noi_effect_not_supplied"
        elif noi_delta == 0:
            noi_value_delta = 0
            net_value_delta = capex_value_effect
            completeness = "complete_zero_noi_effect_stated"
        elif rate is None:
            noi_value_delta = None
            net_value_delta = None
            completeness = "exit_cap_required_to_value_nonzero_noi_effect"
        else:
            noi_value_delta = _money_divide(noi_delta, rate)
            net_value_delta = capex_value_effect + noi_value_delta
            completeness = "complete"

        value_destruction = net_value_delta is not None and net_value_delta < 0
        if net_value_delta is None:
            classification = "incomplete_value_effect"
        elif net_value_delta < 0:
            classification = "value_destruction"
        elif net_value_delta > 0:
            classification = "value_creation"
        else:
            classification = "value_neutral"

        life_text = str(life_effect).casefold() if life_effect is not None else ""
        life_risk_flag = any(
            term in life_text
            for term in ("short", "reduce", "lower", "worse", "defer", "unknown")
        )
        normalized_cap = float(rate) if rate is not None else None
        figures = [
            {
                "figure": "capex_delta_cents",
                "value": capex_delta,
                "basis_tag": "caller-stated option; negative is savings",
            },
            {
                "figure": "capex_value_effect_cents",
                "value": capex_value_effect,
                "basis_tag": "arithmetic: -capex_delta_cents",
            },
            {
                "figure": "noi_delta_cents",
                "value": noi_delta,
                "basis_tag": "caller-stated annual NOI effect; null means unknown",
            },
            {
                "figure": "noi_value_delta_cents",
                "value": noi_value_delta,
                "basis_tag": (
                    "capitalization math: annual NOI delta / stated exit cap"
                    if noi_value_delta is not None
                    else "not calculated; insufficient stated evidence"
                ),
            },
            {
                "figure": "net_value_delta_cents",
                "value": net_value_delta,
                "basis_tag": (
                    "capex value effect + income value effect"
                    if net_value_delta is not None
                    else "not calculated; no zero-NOI assumption imposed"
                ),
            },
        ]

        return {
            "report_type": "ve_option",
            "desc": desc,
            "capex_delta_cents": capex_delta,
            "noi_delta_cents": noi_delta,
            "life_effect": life_effect,
            "exit_cap": normalized_cap,
            "exit_cap_interpretation": rate_interpretation,
            "capex_value_effect_cents": capex_value_effect,
            "noi_value_delta_cents": noi_value_delta,
            "net_value_delta_cents": net_value_delta,
            "value_destruction": value_destruction,
            "classification": classification,
            "calculation_status": completeness,
            "life_effect_risk_flag": life_risk_flag,
            "figures": figures,
            "formula": (
                "net value delta = (-capex delta) + (annual NOI delta / exit cap)"
            ),
            "review_flags": _professional_flags(),
            "honesty": (
                "This is cost-versus-capitalized-NOI arithmetic, not a bid, appraisal, "
                "design approval, useful-life opinion, or field verification. GC, "
                "architect, engineer, and inspector review remain required."
            ),
        }
    except Exception as exc:
        return {"error": f"ve_option: {exc}"}


def percent_complete(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep invoice, field-inspection, and schedule progress visibly separate."""

    try:
        if not isinstance(evidence, Mapping):
            raise ValueError("evidence must be an object")
        invoiced = _cents(evidence.get("invoiced_cents"), "evidence.invoiced_cents")
        budget = _cents(
            evidence.get("budget_cents"), "evidence.budget_cents", positive=True
        )
        if invoiced < 0:
            raise ValueError("evidence.invoiced_cents must be non-negative")

        invoice_pct_decimal = Decimal(invoiced) * Decimal(100) / Decimal(budget)
        invoice_pct = _pct_float(invoice_pct_decimal)
        inspection_raw = evidence.get("inspection_pct")
        schedule_raw = evidence.get("schedule_pct")
        inspection_decimal: Decimal | None = None
        schedule_decimal: Decimal | None = None
        inspection_interpretation: str | None = None
        schedule_interpretation: str | None = None
        if inspection_raw is not None:
            inspection_decimal, inspection_interpretation = _pct(
                inspection_raw, "evidence.inspection_pct"
            )
        if schedule_raw is not None:
            schedule_decimal, schedule_interpretation = _pct(
                schedule_raw, "evidence.schedule_pct"
            )
        inspection_pct = (
            _pct_float(inspection_decimal) if inspection_decimal is not None else None
        )
        schedule_pct = _pct_float(schedule_decimal) if schedule_decimal is not None else None

        views: dict[str, dict[str, Any]] = {
            "invoice_supported": {
                "pct": invoice_pct,
                "percent": invoice_pct,
                "basis": "invoice-supported",
                "basis_tag": "invoice-supported; not field-verified",
                "evidence": {
                    "invoiced_cents": invoiced,
                    "budget_cents": budget,
                },
                "gc_review_required": True,
                "architect_review_required": False,
                "engineer_review_required": False,
                "inspector_review_required": False,
            },
            "field_verified": {
                "pct": inspection_pct,
                "percent": inspection_pct,
                "basis": "field-verified" if inspection_pct is not None else "not supplied",
                "basis_tag": (
                    "field-verified to caller-stated inspection percent"
                    if inspection_pct is not None
                    else "no field-verification evidence supplied"
                ),
                "input_interpretation": inspection_interpretation,
                "gc_review_required": True,
                "architect_review_required": True,
                "engineer_review_required": True,
                "inspector_review_required": True,
            },
            "schedule_reported": {
                "pct": schedule_pct,
                "percent": schedule_pct,
                "basis": "schedule-reported" if schedule_pct is not None else "not supplied",
                "basis_tag": (
                    "schedule-reported; not invoice-supported or field-verified"
                    if schedule_pct is not None
                    else "no schedule-progress evidence supplied"
                ),
                "input_interpretation": schedule_interpretation,
                "gc_review_required": True,
                "architect_review_required": True,
                "engineer_review_required": False,
                "inspector_review_required": False,
            },
        }

        available = {
            "invoice_supported": invoice_pct,
            **(
                {"field_verified": inspection_pct}
                if inspection_pct is not None
                else {}
            ),
            **(
                {"schedule_reported": schedule_pct}
                if schedule_pct is not None
                else {}
            ),
        }
        pairwise: dict[str, float] = {}
        names = list(available)
        for left_index, left in enumerate(names):
            for right in names[left_index + 1 :]:
                pairwise[f"{left}_vs_{right}"] = round(
                    abs(float(available[left]) - float(available[right])), 2
                )
        divergence = round(max(available.values()) - min(available.values()), 2)
        divergence_flag = divergence > DIVERGENCE_THRESHOLD_PCT_POINTS

        return {
            "report_type": "percent_complete_reconciliation",
            "invoiced_cents": invoiced,
            "budget_cents": budget,
            "invoice_supported_pct": invoice_pct,
            "field_verified_pct": inspection_pct,
            "schedule_reported_pct": schedule_pct,
            "views": views,
            "basis_tags": {
                name: view["basis_tag"] for name, view in views.items()
            },
            "pairwise_gaps_pct_points": pairwise,
            "divergence_pct_points": divergence,
            "divergence_flag": divergence_flag,
            "divergence_convention": DIVERGENCE_CONVENTION.copy(),
            "verified_percent_complete": inspection_pct,
            "verified_basis_tag": (
                "field-verified to caller-stated inspection evidence"
                if inspection_pct is not None
                else "not available; invoices and schedule do not create field verification"
            ),
            "over_budget_invoice_flag": invoiced > budget,
            "review_flags": _professional_flags(),
            "honesty": (
                "No blended percent is asserted. Invoice-supported, field-verified, and "
                "schedule-reported figures are different evidence classes. The "
                "field-verified figure never exceeds the inspection evidence supplied."
            ),
        }
    except Exception as exc:
        return {"error": f"percent_complete: {exc}"}


__all__ = [
    "DIVERGENCE_CONVENTION",
    "DIVERGENCE_THRESHOLD_PCT_POINTS",
    "percent_complete",
    "ve_option",
]
