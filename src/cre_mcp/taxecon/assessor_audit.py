"""Assessor-record discrepancy and appeal-signal screening."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.taxecon.reassessment import VERIFY_MESSAGE


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _parcel(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    """Accept an OwnerRecord dump, a parcel wrapper, or a parcel dict."""

    parcels = record.get("parcels")
    if isinstance(parcels, Sequence) and not isinstance(parcels, (str, bytes)):
        for item in parcels:
            if isinstance(item, Mapping):
                return item, "owner_record.parcels[0]"
    nested = record.get("parcel")
    if isinstance(nested, Mapping):
        return nested, "record.parcel"
    return record, "record"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).casefold().replace("_", " ").replace("-", " ").split())
    return normalized or None


def _discrepancy(
    *,
    field: str,
    assessor_value: Any,
    stated_value: Any,
    direction: str,
    appeal_signal: bool,
    reason: str,
    difference: float | None = None,
) -> dict[str, Any]:
    return {
        "field": field,
        "assessor_value": assessor_value,
        "stated_value": stated_value,
        "difference": round(difference, 2) if difference is not None else None,
        "direction_of_tax_impact": direction,
        "appeal_signal": appeal_signal,
        "reason": reason,
        "next_step": (
            "Obtain the assessor property card, supporting measurements/classification, and dated "
            "market evidence; preserve the local appeal deadline."
        ),
    }


def _comp_psf_band(stated_facts: Mapping[str, Any]) -> tuple[float | None, float | None, Any]:
    raw = _first(
        stated_facts,
        (
            "assessed_value_psf_comps",
            "comp_value_psf",
            "comparable_value_psf",
            "market_value_psf",
            "comps_psf",
        ),
    )
    if isinstance(raw, Mapping):
        low = _number(raw.get("low"))
        high = _number(raw.get("high"))
        base = _number(raw.get("base"))
        return low or base, high or base, raw
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = [number for item in raw if (number := _number(item)) is not None and number >= 0]
        return (min(values), max(values), raw) if values else (None, None, raw)
    number = _number(raw)
    return number, number, raw


def audit_assessor_record(
    record: dict[str, Any],
    stated_facts: dict[str, Any],
) -> dict[str, Any]:
    """Compare assessor facts with listing/lease facts and surface appeal signals.

    The function does not decide that an assessment is wrong or that an appeal
    will succeed.  It identifies factual conflicts that merit document review.
    """

    if not isinstance(record, Mapping):
        raise ValueError("record must be a plain dictionary")
    if not isinstance(stated_facts, Mapping):
        raise ValueError("stated_facts must be a plain dictionary")

    parcel, record_shape = _parcel(record)
    discrepancies: list[dict[str, Any]] = []
    fields_compared: list[str] = []

    assessor_sf = _number(
        _first(parcel, ("building_sqft", "building_sf", "square_feet", "sqft", "gross_building_area"))
    )
    stated_sf = _number(
        _first(
            stated_facts,
            ("building_sqft", "building_sf", "square_feet", "sqft", "rentable_sqft", "listing_sqft"),
        )
    )
    if assessor_sf is not None and stated_sf is not None:
        fields_compared.append("building_sqft")
        difference = assessor_sf - stated_sf
        tolerance = max(abs(stated_sf) * 0.01, 1.0)
        if abs(difference) > tolerance:
            over = difference > 0
            discrepancies.append(
                _discrepancy(
                    field="building_sqft",
                    assessor_value=assessor_sf,
                    stated_value=stated_sf,
                    difference=difference,
                    direction=(
                        "potential over-assessment: assessor records more building area"
                        if over
                        else "potential under-assessment/future increase: assessor records less building area"
                    ),
                    appeal_signal=over,
                    reason=(
                        "Assessor square footage exceeds the stated physical area. Verify gross, "
                        "rentable, and taxable-area definitions before treating this as an error."
                        if over
                        else "The stated area exceeds the assessor record; correction could increase taxable value."
                    ),
                )
            )

    assessor_year = _number(_first(parcel, ("year_built", "built_year", "construction_year")))
    stated_year = _number(
        _first(stated_facts, ("year_built", "built_year", "construction_year", "listing_year_built"))
    )
    if assessor_year is not None and stated_year is not None:
        fields_compared.append("year_built")
        difference = assessor_year - stated_year
        if difference != 0:
            assessor_newer = difference > 0
            discrepancies.append(
                _discrepancy(
                    field="year_built",
                    assessor_value=int(assessor_year),
                    stated_value=int(stated_year),
                    difference=difference,
                    direction=(
                        "possible upward tax impact: assessor treats improvements as newer"
                        if assessor_newer
                        else "indeterminate/lower-value signal: assessor treats improvements as older"
                    ),
                    appeal_signal=assessor_newer,
                    reason=(
                        "A newer assessor year can overstate remaining economic life, but renovation/effective-age "
                        "fields may explain the difference; verify the property card and permits."
                    ),
                )
            )

    assessor_use_raw = _first(parcel, ("use_code", "use", "property_use", "property_type", "class_code"))
    stated_use_raw = _first(
        stated_facts,
        ("use_code", "use", "property_use", "property_type", "listing_property_type", "lease_use"),
    )
    assessor_use = _text(assessor_use_raw)
    stated_use = _text(stated_use_raw)
    if assessor_use is not None and stated_use is not None:
        fields_compared.append("use_code")
        if assessor_use != stated_use and assessor_use not in stated_use and stated_use not in assessor_use:
            discrepancies.append(
                _discrepancy(
                    field="use_code",
                    assessor_value=assessor_use_raw,
                    stated_value=stated_use_raw,
                    direction="indeterminate; the wrong assessment class can raise or lower assessed value",
                    appeal_signal=True,
                    reason=(
                        "Assessor use/class differs from the stated operating use. Classification rules are local, "
                        "so confirm legal use, occupancy, and the assessor's code definition."
                    ),
                )
            )

    assessor_units = _number(_first(parcel, ("units", "unit_count", "number_of_units")))
    stated_units = _number(
        _first(stated_facts, ("units", "unit_count", "number_of_units", "listing_units", "lease_units"))
    )
    if assessor_units is not None and stated_units is not None:
        fields_compared.append("units")
        difference = assessor_units - stated_units
        if difference != 0:
            over = difference > 0
            discrepancies.append(
                _discrepancy(
                    field="units",
                    assessor_value=assessor_units,
                    stated_value=stated_units,
                    difference=difference,
                    direction=(
                        "potential over-assessment: assessor records more units"
                        if over
                        else "potential under-assessment/future increase: assessor records fewer units"
                    ),
                    appeal_signal=over,
                    reason=(
                        "Unit-count mismatch can change income/cost valuation inputs; distinguish legal, occupied, "
                        "and physically configured units."
                    ),
                )
            )

    assessed_value = _number(_first(parcel, ("assessed_value", "total_assessed_value", "market_value")))
    comp_low, comp_high, comp_raw = _comp_psf_band(stated_facts)
    assessed_psf: float | None = None
    if assessed_value is not None and assessor_sf is not None and assessor_sf > 0:
        assessed_psf = assessed_value / assessor_sf
        if comp_high is not None:
            fields_compared.append("assessed_value_psf")
            if assessed_psf > comp_high:
                discrepancies.append(
                    _discrepancy(
                        field="assessed_value_psf",
                        assessor_value=round(assessed_psf, 2),
                        stated_value=comp_raw,
                        difference=assessed_psf - comp_high,
                        direction="potential over-assessment: assessed value per sf exceeds stated comp ceiling",
                        appeal_signal=True,
                        reason=(
                            "The assessor-implied value per square foot exceeds the supplied comparable band. "
                            "Confirm that assessed value and comp values use the same assessment ratio, date, rights, "
                            "property type, and square-footage definition."
                        ),
                    )
                )

    appeal_signals = [item for item in discrepancies if item["appeal_signal"]]
    missing_inputs = [
        field
        for field, assessor_value, stated_value in (
            ("building_sqft", assessor_sf, stated_sf),
            ("year_built", assessor_year, stated_year),
            ("use_code", assessor_use, stated_use),
            ("units", assessor_units, stated_units),
        )
        if assessor_value is None or stated_value is None
    ]
    return {
        "status": "REVIEW" if discrepancies else "NO_DISCREPANCY_FOUND",
        "record_shape": record_shape,
        "fields_compared": fields_compared,
        "missing_or_uncompared_fields": missing_inputs,
        "discrepancies": discrepancies,
        "appeal_signal_count": len(appeal_signals),
        "appeal_signals": appeal_signals,
        "assessor_implied_value_psf": round(assessed_psf, 2) if assessed_psf is not None else None,
        "caveats": [
            "A discrepancy is a diligence or appeal signal, not proof of assessor error or appeal value.",
            "Listing and lease facts can use different area, unit, age, and use definitions than the assessor.",
            VERIFY_MESSAGE,
        ],
        "assumption_sheet": [
            {"driver": "record", "value": dict(record), "source": "assessor_record_provided"},
            {"driver": "stated_facts", "value": dict(stated_facts), "source": "listing_or_lease_provided"},
        ],
        "professional_review_required": True,
        "professional_review_flag": True,
        "verify_with_county_assessor_or_tax_counsel_before_reliance": True,
        "verification_message": VERIFY_MESSAGE,
    }


__all__ = ["audit_assessor_record"]
