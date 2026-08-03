"""Nearby branded-POI and co-tenancy enrichment from OpenStreetMap."""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any

from curl_cffi import requests

from cre_mcp.source_rights.gate import require_source, require_url
from cre_mcp.source_rights.output import safe_error_message

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6_371_008.8
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE_MAX_ENTRIES = 256
_USER_AGENT = "MedawarCRE/1.0 (max@efreedom.com)"
_OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

_CacheKey = tuple[float, float, int]
_CACHE: dict[_CacheKey, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()

_TRAFFIC_DRIVER_CATEGORIES = {
    "cafe",
    "coffee",
    "coffee_shop",
    "fast_food",
    "supermarket",
    "grocery",
    "convenience",
    "pharmacy",
    "chemist",
    "department_store",
    "bank",
    "fuel",
    "gym",
    "fitness_centre",
}
_BIG_BOX_CATEGORIES = {
    "big_box",
    "big_box_store",
    "hypermarket",
    "warehouse_club",
    "wholesale",
}
_BIG_BOX_BRANDS = {
    "bj's wholesale club",
    "costco",
    "home depot",
    "ikea",
    "lowe's",
    "sam's club",
    "target",
    "walmart",
}


def _normalized(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance between two WGS84 points in meters."""
    first_latitude = math.radians(lat1)
    second_latitude = math.radians(lat2)
    latitude_delta = second_latitude - first_latitude
    longitude_delta = math.radians(lon2 - lon1)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))


def _cache_key(lat: float, lon: float, radius_m: int) -> _CacheKey:
    return (round(lat, 5), round(lon, 5), radius_m)


def _cache_get(
    key: _CacheKey,
    *,
    ttl_seconds: int,
) -> list[dict[str, Any]] | None:
    if ttl_seconds <= 0:
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        cached_at, results = entry
        if now - cached_at >= ttl_seconds:
            del _CACHE[key]
            return None
        return [dict(result) for result in results]


def _cache_set(
    key: _CacheKey,
    results: list[dict[str, Any]],
    *,
    ttl_seconds: int,
) -> None:
    if ttl_seconds <= 0:
        return
    now = time.monotonic()
    with _CACHE_LOCK:
        expired = [
            cache_key
            for cache_key, (cached_at, _) in _CACHE.items()
            if now - cached_at >= ttl_seconds
        ]
        for cache_key in expired:
            del _CACHE[cache_key]
        if len(_CACHE) >= _CACHE_MAX_ENTRIES and key not in _CACHE:
            oldest = min(_CACHE, key=lambda cache_key: _CACHE[cache_key][0])
            del _CACHE[oldest]
        _CACHE[key] = (now, [dict(result) for result in results])


def _coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    latitude = element.get("lat")
    longitude = element.get("lon")
    if latitude is None or longitude is None:
        center = element.get("center")
        if not isinstance(center, dict):
            return None
        latitude = center.get("lat")
        longitude = center.get("lon")
    try:
        parsed_latitude = float(latitude)
        parsed_longitude = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90 <= parsed_latitude <= 90 and -180 <= parsed_longitude <= 180):
        return None
    return parsed_latitude, parsed_longitude


def _category(tags: dict[str, Any]) -> str:
    for key in ("shop", "amenity", "cuisine", "leisure"):
        value = tags.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown"


def _parse_elements(
    elements: object,
    subject_lat: float,
    subject_lon: float,
) -> list[dict[str, Any]]:
    if not isinstance(elements, list):
        return []
    results: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue
        brand = str(tags.get("brand") or "").strip()
        coordinates = _coordinates(element)
        if not brand or coordinates is None:
            continue
        try:
            osm_id = int(element["id"])
        except (KeyError, TypeError, ValueError):
            continue
        latitude, longitude = coordinates
        results.append(
            {
                "brand": brand,
                "category": _category(tags),
                "distance_m": int(
                    round(_haversine_m(subject_lat, subject_lon, latitude, longitude))
                ),
                "lat": latitude,
                "lon": longitude,
                "osm_id": osm_id,
            }
        )
    results.sort(key=lambda result: result["distance_m"])
    return results


def nearby_brands(
    lat: float,
    lon: float,
    radius_m: int = 800,
    limit: int = 60,
) -> list[dict]:
    """Return branded OSM points of interest near a coordinate, closest first.

    All Overpass and response errors are treated as unavailable enrichment. The
    mirrors are tried in order and a total network failure returns an empty list.
    """
    try:
        latitude = float(lat)
        longitude = float(lon)
        radius = int(radius_m)
        result_limit = int(limit)
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or radius <= 0
            or result_limit <= 0
        ):
            return []

        # Rights are checked before even consulting cached source data.
        record = require_source("overpass")
        cache_ttl = min(
            _CACHE_TTL_SECONDS,
            int(record.operating_policy.memory_cache_ttl_seconds) if record else 0,
        )
        key = _cache_key(latitude, longitude, radius)
        cached = _cache_get(key, ttl_seconds=cache_ttl)
        if cached is not None:
            return cached[:result_limit]

        query = (
            f'[out:json][timeout:25];nwr(around:{radius},{latitude:.7f},'
            f'{longitude:.7f})["brand"];out center 60;'
        )
        for endpoint in _OVERPASS_ENDPOINTS:
            try:
                # Re-check at the direct socket boundary for every mirror.
                require_url(endpoint, method="POST")
                response = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": _USER_AGENT},
                    timeout=30,
                    allow_redirects=False,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Overpass mirror returned HTTP %s: %s",
                        response.status_code,
                        endpoint,
                    )
                    continue
                payload = response.json()
                if not isinstance(payload, dict):
                    continue
                results = _parse_elements(payload.get("elements"), latitude, longitude)
                if not results:
                    continue
                _cache_set(key, results, ttl_seconds=cache_ttl)
                return results[:result_limit]
            except Exception as exc:
                logger.warning(
                    "Overpass mirror failed at %s: %s",
                    endpoint,
                    safe_error_message(exc),
                )
        return []
    except Exception as exc:
        logger.warning("Nearby-brand enrichment failed: %s", safe_error_message(exc))
        return []


def classify_anchor(
    poi: dict,
    subject_category: str | None = None,
) -> str:
    """Classify a branded POI as a complementary anchor, competitor, or neutral."""
    category = _normalized(poi.get("category"))
    normalized_subject = _normalized(subject_category)
    if normalized_subject and category == normalized_subject:
        return "competitor"

    brand = str(poi.get("brand") or "").strip().casefold()
    is_big_box = (
        category in _BIG_BOX_CATEGORIES
        or category.startswith("big_box_")
        or brand in _BIG_BOX_BRANDS
    )
    if category in _TRAFFIC_DRIVER_CATEGORIES or is_big_box:
        return "complementary_anchor"
    return "neutral"


def trade_area_anchors(
    lat: float,
    lon: float,
    radius_m: int = 800,
    subject_category: str | None = None,
) -> dict:
    """Summarize nearby anchors and same-category competition for site scoring."""
    pois = nearby_brands(lat, lon, radius_m=radius_m)
    complementary: list[dict[str, Any]] = []
    competitors: list[dict[str, Any]] = []
    for poi in pois:
        classification = classify_anchor(poi, subject_category)
        if classification == "complementary_anchor":
            complementary.append(poi)
        elif classification == "competitor":
            competitors.append(poi)

    brands = list(dict.fromkeys(str(poi["brand"]) for poi in pois))
    if brands:
        summary = f"{', '.join(brands[:3])} within {int(radius_m)}m"
    else:
        summary = f"No branded POIs found within {int(radius_m)}m"
    return {
        "anchor_count": len(complementary),
        "complementary": complementary,
        "competitors": competitors,
        "brands": brands,
        "summary": summary,
    }


__all__ = ["classify_anchor", "nearby_brands", "trade_area_anchors"]
