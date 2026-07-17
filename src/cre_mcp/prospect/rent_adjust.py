"""Transparent, convention-based adjustment of a single rent comparable."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, timezone
import math
from typing import Any


DEFAULT_ADJUSTMENT_CONVENTIONS: dict[str, Any] = {
    "size_curve": {
        "pct_per_10pct_sf_difference": -0.01,
        "max_abs_pct": 0.20,
        "basis": (
            "Apply -1% to the comp rent for each 10% that subject SF exceeds comp SF; "
            "reverse the sign when the subject is smaller, capped at +/-20%."
        ),
    },
    "condition_steps": {
        "order": ["poor", "fair", "average", "good", "excellent"],
        "pct_per_step": 0.03,
        "basis": "Apply 3% per condition step from the comp condition toward the subject condition.",
    },
    "age_of_comp_time_adjustment": {
        "annual_pct": 0.03,
        "max_years": 5.0,
        "days_per_year": 365.0,
        "basis": (
            "Apply simple (not compounded) 3% annual growth from signed date to the effective date, "
            "capped at five years."
        ),
    },
    "range": {
        "pct_around_adjusted": 0.05,
        "basis": "Report a mechanical +/-5% range around the adjusted point estimate.",
    },
}


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000.0 if abs(float(value)) >= 100_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _merge_conventions(overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    conventions = deepcopy(DEFAULT_ADJUSTMENT_CONVENTIONS)
    if overrides is None:
        return conventions
    if not isinstance(overrides, Mapping):
        raise TypeError("adjustments must be an object or null")
    unknown_sections = sorted(set(overrides) - set(conventions))
    if unknown_sections:
        raise ValueError("unrecognized adjustment convention sections: " + ", ".join(unknown_sections))
    for section, values in overrides.items():
        if not isinstance(values, Mapping):
            raise TypeError(f"adjustments.{section} must be an object")
        unknown_keys = sorted(set(values) - set(conventions[section]))
        if unknown_keys:
            raise ValueError(
                f"unrecognized adjustments.{section} fields: " + ", ".join(unknown_keys)
            )
        conventions[section].update(values)
    return conventions


def _checked_number(
    conventions: Mapping[str, Any], section: str, field: str, *, minimum: float | None = None
) -> float:
    number = _as_number(conventions[section].get(field))
    if number is None or (minimum is not None and number < minimum):
        qualifier = f" at least {minimum}" if minimum is not None else " numeric"
        raise ValueError(f"adjustments.{section}.{field} must be{qualifier}")
    return number


def _line(
    factor: str,
    adjustment_pct: float,
    rent_psf: float,
    arithmetic: str,
    basis: str,
) -> dict[str, Any]:
    return {
        "factor": factor,
        "adjustment_pct": adjustment_pct,
        "adjustment_psf": round(rent_psf * adjustment_pct, 4),
        "arithmetic": arithmetic,
        "convention_basis": basis,
    }


def adjust_rent_comp(
    comp: Mapping[str, Any] | None,
    subject: Mapping[str, Any] | None,
    adjustments: Mapping[str, Any] | None = None,
    as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Adjust a comp rent using exposed, intentionally simple conventions.

    Adjustments are additive percentages applied to the original comp rent.
    ``floor`` and ``frontage`` are surfaced as unadjusted when provided because
    the default convention table has no defensible coefficients for them.
    """

    if not isinstance(comp, Mapping):
        raise TypeError("comp must be an object")
    if not isinstance(subject, Mapping):
        raise TypeError("subject must be an object")
    rent_psf = _as_number(comp.get("rent_psf"))
    if rent_psf is None or rent_psf < 0:
        raise ValueError("comp.rent_psf must be a non-negative finite number")

    conventions = _merge_conventions(adjustments)
    size_rate = _checked_number(conventions, "size_curve", "pct_per_10pct_sf_difference")
    size_cap = _checked_number(conventions, "size_curve", "max_abs_pct", minimum=0.0)
    condition_rate = _checked_number(conventions, "condition_steps", "pct_per_step")
    annual_rate = _checked_number(conventions, "age_of_comp_time_adjustment", "annual_pct")
    max_years = _checked_number(
        conventions, "age_of_comp_time_adjustment", "max_years", minimum=0.0
    )
    days_per_year = _checked_number(
        conventions, "age_of_comp_time_adjustment", "days_per_year", minimum=0.000001
    )
    range_pct = _checked_number(conventions, "range", "pct_around_adjusted", minimum=0.0)
    if range_pct > 1.0:
        raise ValueError("adjustments.range.pct_around_adjusted must not exceed 1.0")

    lines: list[dict[str, Any]] = []
    missing_factors: list[str] = []
    unrecognized_inputs: list[str] = []
    allowed_comp_fields = {
        "rent_psf",
        "sf",
        "condition",
        "signed_date",
        "floor",
        "frontage",
        "frontage_ft",
    }
    allowed_subject_fields = {"sf", "condition", "floor", "frontage", "frontage_ft"}
    for field in sorted(set(comp) - allowed_comp_fields, key=str):
        unrecognized_inputs.append(f"comp.{field} was not recognized and was ignored")
    for field in sorted(set(subject) - allowed_subject_fields, key=str):
        unrecognized_inputs.append(f"subject.{field} was not recognized and was ignored")

    comp_sf = _as_number(comp.get("sf"))
    subject_sf = _as_number(subject.get("sf"))
    if comp_sf is None or subject_sf is None:
        missing_factors.append("size_curve (requires numeric comp.sf and subject.sf)")
        if comp.get("sf") is not None and comp_sf is None:
            unrecognized_inputs.append("comp.sf was not numeric")
        if subject.get("sf") is not None and subject_sf is None:
            unrecognized_inputs.append("subject.sf was not numeric")
    elif comp_sf <= 0 or subject_sf <= 0:
        missing_factors.append("size_curve (requires positive comp.sf and subject.sf)")
        unrecognized_inputs.append("non-positive SF was not used")
    else:
        sf_difference_ratio = (subject_sf - comp_sf) / comp_sf
        uncapped = (sf_difference_ratio / 0.10) * size_rate
        size_adjustment = max(-size_cap, min(size_cap, uncapped))
        lines.append(
            _line(
                "size_curve",
                size_adjustment,
                rent_psf,
                (
                    f"(({subject_sf:g} - {comp_sf:g}) / {comp_sf:g}) / 0.10 "
                    f"* {size_rate:g} = {uncapped:.6f}; capped to {size_adjustment:.6f}"
                ),
                str(conventions["size_curve"]["basis"]),
            )
        )

    condition_order = conventions["condition_steps"].get("order")
    if (
        not isinstance(condition_order, list)
        or not condition_order
        or any(not isinstance(item, str) or not item.strip() for item in condition_order)
    ):
        raise ValueError("adjustments.condition_steps.order must be a non-empty list of labels")
    normalized_order = [item.strip().lower() for item in condition_order]
    if len(set(normalized_order)) != len(normalized_order):
        raise ValueError("adjustments.condition_steps.order labels must be unique")
    comp_condition_raw = comp.get("condition")
    subject_condition_raw = subject.get("condition")
    if comp_condition_raw is None or subject_condition_raw is None:
        missing_factors.append("condition_steps (requires comp.condition and subject.condition)")
    else:
        comp_condition = str(comp_condition_raw).strip().lower()
        subject_condition = str(subject_condition_raw).strip().lower()
        if comp_condition not in normalized_order or subject_condition not in normalized_order:
            missing_factors.append("condition_steps (condition label not in exposed order)")
            unrecognized_inputs.append(
                "condition labels must be one of: " + ", ".join(normalized_order)
            )
        else:
            steps = normalized_order.index(subject_condition) - normalized_order.index(comp_condition)
            condition_adjustment = steps * condition_rate
            lines.append(
                _line(
                    "condition_steps",
                    condition_adjustment,
                    rent_psf,
                    f"({normalized_order.index(subject_condition)} - {normalized_order.index(comp_condition)}) * {condition_rate:g} = {condition_adjustment:.6f}",
                    str(conventions["condition_steps"]["basis"]),
                )
            )

    signed_value = comp.get("signed_date")
    if signed_value is None:
        missing_factors.append("age_of_comp_time_adjustment (requires comp.signed_date)")
        effective_date = date.today() if as_of is None else _as_date(as_of)
    else:
        signed_date = _as_date(signed_value)
        effective_date = date.today() if as_of is None else _as_date(as_of)
        if effective_date is None:
            raise ValueError("as_of must be a recognizable date or null")
        if signed_date is None:
            missing_factors.append("age_of_comp_time_adjustment (unrecognized comp.signed_date)")
            unrecognized_inputs.append("comp.signed_date was not a recognized ISO date")
        elif signed_date > effective_date:
            missing_factors.append("age_of_comp_time_adjustment (signed date is after effective date)")
            unrecognized_inputs.append("future comp.signed_date was not adjusted")
        else:
            raw_years = (effective_date - signed_date).days / days_per_year
            years = min(raw_years, max_years)
            time_adjustment = years * annual_rate
            lines.append(
                _line(
                    "age_of_comp_time_adjustment",
                    time_adjustment,
                    rent_psf,
                    f"min({raw_years:.6f}, {max_years:g}) * {annual_rate:g} = {time_adjustment:.6f}",
                    str(conventions["age_of_comp_time_adjustment"]["basis"]),
                )
            )
    if effective_date is None:
        raise ValueError("as_of must be a recognizable date or null")

    for field in ("floor", "frontage", "frontage_ft"):
        if comp.get(field) is not None or subject.get(field) is not None:
            unrecognized_inputs.append(
                f"{field} was supplied but no {field} coefficient exists in the exposed conventions; no adjustment applied"
            )

    total_adjustment_pct = sum(line["adjustment_pct"] for line in lines)
    adjusted_psf = rent_psf * (1.0 + total_adjustment_pct)
    low = adjusted_psf * (1.0 - range_pct)
    high = adjusted_psf * (1.0 + range_pct)
    return {
        "comp_rent_psf": round(rent_psf, 4),
        "adjusted_psf": round(adjusted_psf, 4),
        "adjusted_psf_range": {
            "low": round(low, 4),
            "high": round(high, 4),
            "range_pct": round(range_pct, 6),
        },
        "total_adjustment_pct": round(total_adjustment_pct, 6),
        "adjustments": lines,
        "convention_table": conventions,
        "arithmetic_convention": (
            "Adjustment percentages are additive and each adjustment_psf is based on the original comp rent."
        ),
        "effective_date": effective_date.isoformat(),
        "missing_factors": missing_factors,
        "unrecognized_inputs": unrecognized_inputs,
        "heuristic_label": "HEURISTIC; convention-based and not calibrated to a local rent model",
        "verification_notice": "convention, verify w/ local broker",
    }


__all__ = ["DEFAULT_ADJUSTMENT_CONVENTIONS", "adjust_rent_comp"]
