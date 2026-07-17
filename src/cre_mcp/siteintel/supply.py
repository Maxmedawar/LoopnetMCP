"""Permit-based construction-pipeline signals.

The source permit adapter is intentionally reused from :mod:`cre_mcp.zoning`.
That adapter is coordinate based, so this city-level view documents the city
centroid used as a convention instead of implying citywide permit coverage.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, timezone
from typing import Any

from cre_mcp.http.fetch import FetchClient
from cre_mcp.zoning.permits import permits_near, resolve_permit_source


# Coordinate conventions used only because permits_near requires a point. The
# upstream adapter searches a 500 m circle; this is not a citywide inventory.
CITY_CENTROIDS: dict[str, tuple[float, float]] = {
    "austin": (30.2672, -97.7431),
    "chicago": (41.8781, -87.6298),
    "san_francisco": (37.7749, -122.4194),
    "los_angeles": (34.0522, -118.2437),
    "seattle": (47.6062, -122.3321),
}


# The table is public so analysts can audit and revise feed-specific choices.
# Values are normalized with punctuation converted to spaces before matching.
SUPPLY_TYPE_MAPPINGS: dict[str, dict[str, Any]] = {
    "austin": {
        "dataset_id": "3syk-w9eu",
        "type_fields": ("permit_type", "work_class", "description"),
        "new_construction": ("new construction", "new"),
        "major_renovation": (
            "addition",
            "remodel",
            "renovation",
            "alteration",
        ),
        "size_fields": (
            "total_new_addition_sqft",
            "new_addition_demo_floor_area",
            "remodel_total_sqft",
            "total_existing_bldg_sqft",
        ),
        "size_unit": "square_feet",
    },
    "chicago": {
        "dataset_id": "ydr8-5enu",
        "type_fields": ("permit_type", "work_description"),
        "new_construction": ("permit new construction", "new construction"),
        "major_renovation": (
            "permit renovation alteration",
            "renovation",
            "alteration",
            "addition",
        ),
        "size_fields": ("building_area", "square_feet"),
        "size_unit": "square_feet",
    },
    "san_francisco": {
        "dataset_id": "i98e-djp9",
        "type_fields": ("permit_type_definition", "permit_type", "description"),
        "new_construction": ("new construction", "new construction wood frame"),
        "major_renovation": (
            "additions alterations or repairs",
            "addition",
            "alteration",
            "renovation",
        ),
        "size_fields": ("floor_area", "square_feet"),
        "size_unit": "square_feet",
    },
    "los_angeles": {
        "dataset_id": "pi9x-tg5x",
        "type_fields": ("permit_type", "permit_sub_type", "work_desc"),
        "new_construction": ("bldg new", "new construction"),
        "major_renovation": (
            "bldg addition",
            "bldg alter repair",
            "addition",
            "alteration",
            "major renovation",
        ),
        "size_fields": ("floor_area_l_a_building_code_definition",),
        "size_unit": "square_feet",
    },
    "seattle": {
        "dataset_id": "76t5-zqzr",
        "type_fields": ("permittypemapped", "permittypedesc", "description"),
        "new_construction": ("new", "new construction"),
        "major_renovation": (
            "addition alteration",
            "addition",
            "alteration",
            "renovation",
        ),
        "size_fields": ("projectareasqft", "squarefeet"),
        "size_unit": "square_feet",
    },
}

PermitFetcher = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _has_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return f" {phrase} " in f" {text} "


def _classify_permit(
    row: Mapping[str, Any], mapping: Mapping[str, Any]
) -> str | None:
    text = " ".join(
        _normalized(row.get(field))
        for field in mapping["type_fields"]
        if row.get(field) not in (None, "")
    )
    for category in ("new_construction", "major_renovation"):
        for raw_phrase in mapping[category]:
            if _has_phrase(text, _normalized(raw_phrase)):
                return category
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _reported_size(
    row: Mapping[str, Any], mapping: Mapping[str, Any]
) -> tuple[float | None, str | None]:
    for field in mapping["size_fields"]:
        parsed = _number(row.get(field))
        if parsed is not None:
            return parsed, field
    return None, None


def _period(row: Mapping[str, Any], date_field: str) -> str:
    raw = row.get(date_field)
    if raw in (None, ""):
        for fallback in ("issue_date", "issued_date", "issueddate"):
            if row.get(fallback) not in (None, ""):
                raw = row[fallback]
                break
    if isinstance(raw, (date, datetime)):
        return raw.strftime("%Y-%m")
    value = str(raw or "").strip()
    iso_match = re.match(r"^(\d{4})-(\d{2})", value)
    if iso_match:
        return f"{iso_match.group(1)}-{iso_match.group(2)}"
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return "unknown"


def _mapping_public(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in mapping.items()
    }


async def supply_pipeline(
    city: str,
    since_days: int,
    *,
    fetch: FetchClient | None = None,
    permit_fetcher: PermitFetcher | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a point-sampled permit pipeline signal for a documented city.

    ``permit_fetcher`` is an explicit test/integration seam; production defaults
    to the existing read-only ``cre_mcp.zoning.permits.permits_near`` adapter.
    """

    if not isinstance(city, str) or not city.strip():
        return {"error": "city must be a non-empty string"}
    if isinstance(since_days, bool) or not isinstance(since_days, int):
        return {"error": "since_days must be a non-negative integer"}
    if since_days < 0:
        return {"error": "since_days must be a non-negative integer"}

    source = resolve_permit_source(city)
    if source is None or source.key not in SUPPLY_TYPE_MAPPINGS:
        return {
            "status": "UNSUPPORTED",
            "city": city,
            "count": 0,
            "periods": [],
            "mapping_table": {
                key: _mapping_public(value)
                for key, value in SUPPLY_TYPE_MAPPINGS.items()
            },
            "honesty": "permits != deliveries",
        }

    latitude, longitude = CITY_CENTROIDS[source.key]
    adapter = permit_fetcher or permits_near
    try:
        result = adapter(
            latitude,
            longitude,
            source.city,
            since_days,
            fetch=fetch,
        )
        permit_result = await result if inspect.isawaitable(result) else result
    except Exception as exc:
        return {"error": f"permit feed failed: {exc}"}

    if not isinstance(permit_result, Mapping):
        return {"error": "permit feed returned a non-object response"}
    if permit_result.get("error"):
        return {"error": f"permit feed failed: {permit_result['error']}"}
    if permit_result.get("status") == "UNSUPPORTED":
        return dict(permit_result)

    raw_permits = permit_result.get("permits", [])
    if not isinstance(raw_permits, list):
        return {"error": "permit feed permits must be a list"}

    mapping = SUPPLY_TYPE_MAPPINGS[source.key]
    buckets: dict[str, dict[str, Any]] = {}
    qualifying = 0
    reported_size_total = 0.0
    size_records = 0
    size_fields_seen: set[str] = set()

    for raw_row in raw_permits:
        if not isinstance(raw_row, Mapping):
            continue
        category = _classify_permit(raw_row, mapping)
        if category is None:
            continue
        qualifying += 1
        period = _period(raw_row, source.date_field)
        bucket = buckets.setdefault(
            period,
            {
                "period": period,
                "permit_count": 0,
                "new_construction": 0,
                "major_renovation": 0,
                "reported_size_sf": 0.0,
                "size_records": 0,
            },
        )
        bucket["permit_count"] += 1
        bucket[category] += 1
        size, size_field = _reported_size(raw_row, mapping)
        if size is not None:
            bucket["reported_size_sf"] += size
            bucket["size_records"] += 1
            reported_size_total += size
            size_records += 1
            if size_field is not None:
                size_fields_seen.add(size_field)

    periods = [buckets[key] for key in sorted(buckets)]
    retrieved = today or datetime.now(timezone.utc).date()
    endpoint = permit_result.get("source_endpoint") or source.endpoint
    return {
        "status": "OK",
        "city": source.city,
        "since_days": since_days,
        "count": qualifying,
        "raw_permit_count": len(raw_permits),
        "periods": periods,
        "totals": {
            "qualifying_permits": qualifying,
            "new_construction": sum(item["new_construction"] for item in periods),
            "major_renovation": sum(item["major_renovation"] for item in periods),
            "reported_size_sf": reported_size_total,
            "size_records": size_records,
            "size_fields_seen": sorted(size_fields_seen),
        },
        "type_mapping": _mapping_public(mapping),
        "source": {
            "feed": endpoint,
            "dataset_id": source.dataset_id,
            "dataset_name": source.dataset_name,
            "retrieved_date": retrieved.isoformat(),
        },
        "spatial_convention": {
            "label": (
                "City-center point convention; upstream permits_near covers only "
                "a 500 m radius, not the whole city"
            ),
            "centroid": {"lat": latitude, "lon": longitude},
            "radius_m": permit_result.get("radius_m", 500),
        },
        "honesty": (
            "permits != deliveries; classifications follow the exposed feed-specific "
            "mapping, and reported size totals mix only the fields named above"
        ),
    }


__all__ = [
    "CITY_CENTROIDS",
    "SUPPLY_TYPE_MAPPINGS",
    "supply_pipeline",
]
