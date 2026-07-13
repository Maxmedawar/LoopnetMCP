"""Cross-source listing deduplication."""

import re
from typing import Any

from cre_mcp.models import Listing, ListingRef

_USPS_SUFFIXES = {
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "COURT": "CT",
    "DRIVE": "DR",
    "HIGHWAY": "HWY",
    "LANE": "LN",
    "PARKWAY": "PKWY",
    "ROAD": "RD",
    "STREET": "ST",
}
_SOURCE_PRIORITY = {
    "loopnet": 10,
    "crexi": 20,
}
_COMPLETENESS_EXCLUSIONS = {
    "also_listed_on",
    "raw",
    "refs",
    "source",
    "source_id",
}


def _normalize_component(value: str) -> str:
    value = re.sub(r"[^A-Z0-9]+", " ", value.upper())
    return re.sub(r"\s+", " ", value).strip()


def normalize_address(address: str) -> str:
    """Normalize a street address for deterministic matching."""
    normalized = address.upper()
    normalized = re.sub(
        r"\b(?:SUITE|STE)\b(?:[\s.,#-]+[A-Z0-9-]+)?",
        " ",
        normalized,
    )
    normalized = _normalize_component(normalized)
    for full, abbreviation in _USPS_SUFFIXES.items():
        normalized = re.sub(rf"\b{full}\b", abbreviation, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def dedupe_key(listing: Listing) -> str:
    """Build the best available cross-source identity key for a listing."""
    city = _normalize_component(listing.city)
    state = _normalize_component(listing.state)
    if listing.address.strip():
        zip_match = re.search(r"\d{5}", listing.zip_code or "")
        zip_code = zip_match.group(0) if zip_match else ""
        return "|".join(
            (normalize_address(listing.address), city, state, zip_code)
        )
    return "|".join((_normalize_component(listing.name), city, state))


def _has_value(value: Any) -> bool:
    return value is not None and value is not False and value not in ("", [], {})


def _completeness(listing: Listing) -> int:
    return sum(
        _has_value(value)
        for field_name, value in listing.model_dump().items()
        if field_name not in _COMPLETENESS_EXCLUSIONS
    )


def _base_and_other(a: Listing, b: Listing) -> tuple[Listing, Listing]:
    a_rank = (_completeness(a), _SOURCE_PRIORITY.get(a.source.lower(), 0))
    b_rank = (_completeness(b), _SOURCE_PRIORITY.get(b.source.lower(), 0))
    return (b, a) if b_rank > a_rank else (a, b)


def _union_refs(*groups: list[ListingRef]) -> list[ListingRef]:
    refs: list[ListingRef] = []
    seen: set[tuple[str, str, str | None]] = set()
    for group in groups:
        for ref in group:
            key = (ref.source, ref.source_id, ref.url)
            if key not in seen:
                refs.append(ref)
                seen.add(key)
    return refs


def merge_listings(a: Listing, b: Listing) -> Listing:
    """Merge colliding listings without discarding source provenance."""
    base, other = _base_and_other(a, b)
    data = base.model_dump()
    other_data = other.model_dump()

    for field_name in Listing.model_fields:
        if field_name in {
            "also_listed_on",
            "raw",
            "refs",
            "source",
            "source_id",
        }:
            continue
        if not _has_value(data[field_name]) and _has_value(other_data[field_name]):
            data[field_name] = other_data[field_name]

    data["refs"] = [
        ref.model_dump() for ref in _union_refs(base.refs, other.refs)
    ]
    other_sources = {
        *base.also_listed_on,
        *other.also_listed_on,
        other.source,
    }
    other_sources.discard(base.source)
    data["also_listed_on"] = sorted(other_sources)
    data["raw"] = {**other.raw, **base.raw}
    return Listing.model_validate(data)


def dedupe_listings(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Collapse duplicate keys and return the number of removed records."""
    merged: list[Listing] = []
    key_to_index: dict[str, int] = {}
    deduped = 0

    for listing in listings:
        key = dedupe_key(listing)
        if key in key_to_index:
            index = key_to_index[key]
            merged[index] = merge_listings(merged[index], listing)
            deduped += 1
        else:
            key_to_index[key] = len(merged)
            merged.append(listing)
    return merged, deduped


def merge(listings: list[Listing]) -> tuple[list[Listing], int]:
    """Compatibility name used by the registry."""
    return dedupe_listings(listings)
