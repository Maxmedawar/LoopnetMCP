"""Conventional ring trade areas with lightweight OSM retail context.

This module deliberately does not manufacture drive-time polygons or fetch
demographics.  It combines transparent 1/3/5-mile rings with the repository's
existing OpenStreetMap enrichment and leaves Census values as caller inputs.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from cre_mcp.enrichment.nearby import trade_area_anchors

RING_MILES: tuple[int, ...] = (1, 3, 5)
METERS_PER_MILE = 1_609.344
RING_CONVENTION_LABEL = (
    "rings are a convention; drive-time isochrones need a routing engine — flagged gap"
)


def _coordinate(value: object, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number between {lower:g} and {upper:g}")
    try:
        coordinate = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be a finite number between {lower:g} and {upper:g}"
        ) from exc
    if not math.isfinite(coordinate) or not lower <= coordinate <= upper:
        raise ValueError(f"{name} must be a finite number between {lower:g} and {upper:g}")
    return coordinate


def _optional_nonnegative(value: object, name: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative finite number when provided")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be a non-negative finite number when provided"
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a non-negative finite number when provided")
    if name == "population":
        if not number.is_integer():
            raise ValueError("population must be a whole number when provided")
        return int(number)
    return number


def _gravity_notes(anchors: dict[str, Any], radius_m: int) -> list[str]:
    summary = str(anchors.get("summary") or "").strip()
    anchor_count = anchors.get("anchor_count")
    competitors = anchors.get("competitors")
    competitor_count = len(competitors) if isinstance(competitors, list) else 0

    notes: list[str] = []
    if summary:
        notes.append(summary)
    if isinstance(anchor_count, int):
        notes.append(
            f"OSM identifies {anchor_count} complementary retail anchors within "
            f"the {radius_m}m lookup radius."
        )
    if competitor_count:
        notes.append(f"OSM also identifies {competitor_count} category competitors.")
    notes.append(
        "OSM branded-place coverage is incomplete and is a context signal, not a "
        "complete tenant or sales inventory."
    )
    return notes


def trade_area(
    lat: float,
    lon: float,
    mode: str = "rings",
    population: int | None = None,
    median_household_income: float | None = None,
) -> dict[str, Any]:
    """Build a transparent ring trade-area profile for a site.

    ``population`` and ``median_household_income`` are optional hooks for values
    supplied by a caller.  The repository's existing Census enrichment should
    populate them when available; this module intentionally does not duplicate
    that work.

    Returns an ``{"error": ...}`` dictionary for validation or enrichment
    failures, matching the repository's public boundary convention.
    """
    try:
        latitude = _coordinate(lat, "lat", -90.0, 90.0)
        longitude = _coordinate(lon, "lon", -180.0, 180.0)
        if not isinstance(mode, str) or mode.casefold().strip() != "rings":
            raise ValueError("mode must be 'rings'")
        normalized_population = _optional_nonnegative(population, "population")
        normalized_income = _optional_nonnegative(
            median_household_income, "median_household_income"
        )

        max_radius_m = int(round(max(RING_MILES) * METERS_PER_MILE))
        anchors = trade_area_anchors(latitude, longitude, radius_m=max_radius_m)
        if not isinstance(anchors, dict):
            raise ValueError("OSM anchor enrichment returned an invalid response")
        if "error" in anchors:
            raise ValueError(str(anchors["error"]))

        rings = [
            {
                "radius_miles": miles,
                "radius_m": int(round(miles * METERS_PER_MILE)),
                "area_sq_miles": round(math.pi * miles**2, 3),
            }
            for miles in RING_MILES
        ]
        return {
            "center": {"lat": latitude, "lon": longitude},
            "mode": "rings",
            "rings": rings,
            "convention_label": RING_CONVENTION_LABEL,
            "osm_anchors": anchors,
            "retail_gravity_notes": _gravity_notes(anchors, max_radius_m),
            "osm_source": {
                "name": "OpenStreetMap via cre_mcp.enrichment.nearby",
                "source_url": "https://www.openstreetmap.org/copyright",
                "retrieved_date": date.today().isoformat(),
                "lookup_radius_m": max_radius_m,
            },
            "demographic_inputs": {
                "population": normalized_population,
                "median_household_income": normalized_income,
                "status": (
                    "caller-provided"
                    if normalized_population is not None or normalized_income is not None
                    else "not provided"
                ),
            },
            "demographic_hook": {
                "reference": "existing Census enrichment elsewhere in the repository",
                "scope": "input-only; Census retrieval is intentionally not duplicated here",
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "METERS_PER_MILE",
    "RING_CONVENTION_LABEL",
    "RING_MILES",
    "trade_area",
]
