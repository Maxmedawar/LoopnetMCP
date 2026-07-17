"""Heuristic screening for potentially vacant standalone retail listings."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from cre_mcp.models.listings import Listing

_VACANCY_WEIGHTS: dict[str, float] = {
    "vacant": 0.36,
    "2nd generation": 0.24,
    "2nd gen": 0.24,
    "second generation": 0.24,
    "white box": 0.24,
    "dark": 0.28,
    "former": 0.20,
    "shell": 0.20,
    "available": 0.10,
    "for lease": 0.08,
}
_STRONG_TERMS = {
    "vacant",
    "2nd generation",
    "2nd gen",
    "second generation",
    "white box",
    "dark",
    "former",
    "shell",
}
_STANDALONE_TERMS = (
    "standalone",
    "free standing",
    "freestanding",
    "single tenant",
    "single-tenant",
)


def _field(listing: Listing | Mapping[str, Any], name: str) -> Any:
    if isinstance(listing, Listing):
        return getattr(listing, name, None)
    return listing.get(name)


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).casefold().replace("-", " ")).strip()


def _raw(listing: Listing | Mapping[str, Any]) -> Mapping[str, Any]:
    value = _field(listing, "raw")
    return value if isinstance(value, Mapping) else {}


def _days_on_market(raw: Mapping[str, Any]) -> int | None:
    accepted = {"daysonmarket", "dom", "marketingdays", "listingdays"}
    for key, value in raw.items():
        normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
        if normalized_key not in accepted or isinstance(value, bool):
            continue
        match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            return max(0, int(float(match.group())))
    return None


def detect_vacant(listing: Listing | Mapping[str, Any]) -> dict[str, object]:
    """Return a conservative vacancy screen; all signals require verification."""

    if not isinstance(listing, (Listing, Mapping)):
        raise TypeError("listing must be a Listing or mapping")

    searchable = " ".join(
        _normalized_text(_field(listing, field))
        for field in ("name", "description", "listing_type")
    )
    matched_terms = {
        term for term in _VACANCY_WEIGHTS if _normalized_text(term) in searchable
    }

    property_context = " ".join(
        _normalized_text(_field(listing, field))
        for field in ("property_type", "property_subtype")
    )
    is_retail = "retail" in property_context or "restaurant" in property_context
    is_standalone = any(
        _normalized_text(term) in property_context for term in _STANDALONE_TERMS
    )

    signals: list[str] = [
        f"Listing text contains '{term}'" for term in sorted(matched_terms)
    ]
    confidence = sum(_VACANCY_WEIGHTS[term] for term in matched_terms)

    if is_retail:
        signals.append("Property type indicates retail or restaurant use")
        confidence += 0.15
    if is_standalone:
        signals.append("Property type indicates a standalone building")
        confidence += 0.18

    days_on_market = _days_on_market(_raw(listing))
    if days_on_market is not None and days_on_market >= 120:
        signals.append(f"Long marketing period: {days_on_market} days")
        confidence += 0.12 if days_on_market >= 180 else 0.08

    has_strong_vacancy_signal = bool(matched_terms & _STRONG_TERMS)
    has_weak_vacancy_signal = bool(matched_terms & {"available", "for lease"})
    is_vacant_candidate = has_strong_vacancy_signal or (
        has_weak_vacancy_signal and is_retail and is_standalone
    )
    confidence = round(min(0.95, max(0.0, confidence)), 2)

    signals.append(
        "Heuristic screen only; confirm occupancy and physical condition directly."
    )
    return {
        "is_vacant_candidate": is_vacant_candidate,
        "signals": signals,
        "confidence": confidence,
    }


__all__ = ["detect_vacant"]
