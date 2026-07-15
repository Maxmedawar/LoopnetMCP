"""Conservative matching screen for observed improvements and permit history."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


VERIFICATION_REQUIRED = "code professional verification required"
DISCLAIMER = (
    "Permit-history matching is a text-and-date screen, not a code or title "
    f"opinion; {VERIFICATION_REQUIRED}."
)
YEAR_TOLERANCE = 2

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "building",
    "commercial",
    "for",
    "improvement",
    "install",
    "installed",
    "new",
    "of",
    "permit",
    "property",
    "replace",
    "replaced",
    "replacement",
    "the",
    "to",
    "work",
}

_CATEGORIES: dict[str, tuple[str, ...]] = {
    "addition": ("addition", "expansion", "extend", "square footage"),
    "alteration": ("alteration", "remodel", "renovation", "tenant improvement", "buildout", "build out"),
    "electrical": ("electrical", "electric", "panel", "rewire"),
    "hvac": ("hvac", "air conditioning", "mechanical", "rooftop unit", "rtu", "furnace"),
    "plumbing": ("plumbing", "plumber", "sewer", "water heater"),
    "roof": ("roof", "reroof", "re roof"),
    "sign": ("sign", "signage"),
    "solar": ("solar", "photovoltaic", "pv array"),
    "sprinkler": ("sprinkler", "fire suppression"),
}


def _tokens(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return {word for word in words if len(word) > 2 and word not in _STOP_WORDS}


def _categories(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return {
        category
        for category, phrases in _CATEGORIES.items()
        if any(phrase in normalized for phrase in phrases)
    }


def _year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, date):
        return value.year
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2200 else None
    match = re.search(r"\b(18|19|20|21)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def _permit_rows(value: Any) -> tuple[list[Mapping[str, Any]], str | None]:
    status: str | None = None
    if isinstance(value, Mapping):
        status = str(value.get("status")) if value.get("status") is not None else None
        if "permits" not in value or value.get("permits") is None:
            raise ValueError("permits_near payload permits must be a sequence")
        value = value.get("permits")
    if value is None:
        return [], status
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("permit_history must be a sequence or a permits_near result")
    rows = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("each permit_history item must be a mapping")
        rows.append(row)
    return rows, status


def _permit_text(row: Mapping[str, Any]) -> str:
    values = [
        row.get("type", row.get("permit_type", row.get("work_type"))),
        row.get("desc", row.get("description", row.get("work_description"))),
    ]
    return " ".join(str(value) for value in values if value is not None)


def _permit_date(row: Mapping[str, Any]) -> Any:
    for key in ("date", "issue_date", "issued_date", "issueddate", "permit_date"):
        if row.get(key) is not None:
            return row[key]
    return None


def _match(observed: str, observed_year: int | None, permit: Mapping[str, Any]) -> dict[str, Any] | None:
    permit_text = _permit_text(permit)
    category_overlap = _categories(observed) & _categories(permit_text)
    token_overlap = _tokens(observed) & _tokens(permit_text)
    permit_year = _year(_permit_date(permit))
    date_plausible = (
        observed_year is None
        or permit_year is None
        or abs(observed_year - permit_year) <= YEAR_TOLERANCE
    )
    text_plausible = bool(category_overlap or token_overlap)
    if not text_plausible or not date_plausible:
        return None
    return {
        "permit": dict(permit),
        "category_overlap": sorted(category_overlap),
        "token_overlap": sorted(token_overlap),
        "observed_year": observed_year,
        "permit_year": permit_year,
        "year_difference": (
            abs(observed_year - permit_year)
            if observed_year is not None and permit_year is not None
            else None
        ),
        "basis": "shared work category/text and date within convention when both years are known",
    }


def _unpermitted_work_screen(
    observed_improvements: Sequence[Mapping[str, Any]] | None,
    permit_history: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Flag observed improvements lacking a plausible supplied permit match."""

    if observed_improvements is None:
        observed_improvements = []
    if isinstance(observed_improvements, (str, bytes)) or not isinstance(
        observed_improvements, Sequence
    ):
        raise TypeError("observed_improvements must be a sequence")
    permits, source_status = _permit_rows(permit_history)
    matches: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for index, improvement in enumerate(observed_improvements):
        if not isinstance(improvement, Mapping):
            raise TypeError("each observed improvement must be a mapping")
        description = str(improvement.get("desc") or "").strip()
        if not description:
            raise ValueError("each observed improvement needs desc")
        estimated_year = _year(improvement.get("est_year"))
        plausible = [
            candidate
            for permit in permits
            if (candidate := _match(description, estimated_year, permit)) is not None
        ]
        observed = {
            "index": index,
            "desc": description,
            "est_year": estimated_year,
        }
        if plausible:
            matches.append({"observed_improvement": observed, "plausible_permits": plausible})
        else:
            flags.append(
                {
                    **observed,
                    "reason": (
                        "No supplied permit has a shared work category/text with a compatible "
                        f"year (±{YEAR_TOLERANCE} years when both years are known)."
                    ),
                    "verification": VERIFICATION_REQUIRED,
                    "status": "POTENTIALLY_UNPERMITTED",
                }
            )
    return {
        "status": "FLAGS_FOUND" if flags else "NO_UNMATCHED_IMPROVEMENTS_IN_SUPPLIED_DATA",
        "flags": flags,
        "matches": matches,
        "observed_count": len(observed_improvements),
        "permit_count": len(permits),
        "permit_history_status": source_status,
        "matching_convention": {
            "year_tolerance": YEAR_TOLERANCE,
            "text_rule": "shared normalized work category or non-generic token",
            "limit": "A text match does not establish permit scope, final approval, or code compliance.",
        },
        "disclaimer": DISCLAIMER,
    }


def unpermitted_work_screen(
    observed_improvements: Sequence[Mapping[str, Any]] | None,
    permit_history: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Safe public boundary for the conservative permit-history screen."""

    try:
        return _unpermitted_work_screen(observed_improvements, permit_history)
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["DISCLAIMER", "VERIFICATION_REQUIRED", "YEAR_TOLERANCE", "unpermitted_work_screen"]
