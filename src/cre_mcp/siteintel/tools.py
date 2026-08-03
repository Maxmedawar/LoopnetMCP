"""Plain site-intelligence callables for later FastMCP registration.

This module deliberately has no FastMCP imports, decorators, or registration
side effects.  Each function contains implementation errors at the repository's
stable ``{"error": ...}`` boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.siteintel.dedup import dedupe_listings as _dedupe_listings
from cre_mcp.siteintel.employers import employer_events as _employer_events
from cre_mcp.siteintel.leakage import retail_gap_note as _retail_gap_note
from cre_mcp.siteintel.supply import supply_pipeline as _supply_pipeline
from cre_mcp.siteintel.tradearea import trade_area as _trade_area


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )


def _restricted_warn_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Project complete TX city locations without changing the feed adapter."""
    events = payload.get("events")
    if not isinstance(events, list):
        return payload
    projected: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            return payload
        location = event.get("location")
        if not isinstance(location, str):
            return payload
        parts = [part.strip() for part in location.split(",") if part.strip()]
        county: str | None = None
        if (
            len(parts) == 3
            and parts[1].casefold().endswith(" county")
            and parts[2].casefold() == "tx"
        ):
            city, county = parts[0], parts[1]
            state = "TX"
        elif (
            len(parts) == 2
            and parts[1].casefold() == "tx"
        ):
            state = "TX"
            if parts[0].casefold().endswith(" county"):
                city = None
                county = parts[0]
            else:
                city = parts[0]
        else:
            return payload
        item = dict(event)
        item["location"] = f"{city}, {state}" if city is not None else state
        # County is an independent free-form jurisdiction claim. The exact
        # normalized location above is the sole restricted location carrier.
        item["county"] = None
        projected.append(item)
    result = dict(payload)
    result["events"] = projected
    result["count"] = len(projected)
    return result


def dedupe_listings(
    listings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group only confirmed duplicate listings and surface candidates separately."""

    try:
        return _dedupe_listings(listings)
    except Exception as exc:
        return {"error": str(exc)}


def trade_area_profile(
    lat: float,
    lon: float,
    mode: str = "rings",
) -> dict[str, Any]:
    """Return the conventional ring profile and nearby OSM anchor notes."""

    try:
        return _trade_area(lat, lon, mode)
    except Exception as exc:
        return {"error": str(exc)}


async def supply_pipeline_signal(
    city: str,
    since_days: int = 365,
) -> dict[str, Any]:
    """Return permit-derived pipeline signals, not an inventory forecast."""

    try:
        return await _supply_pipeline(city, since_days)
    except Exception as exc:
        return {"error": str(exc)}


async def employer_warn_events(
    state: str,
    since: str | None = None,
) -> dict[str, Any]:
    """Return normalized public WARN events for a supported state feed."""

    try:
        result = await _employer_events(state, since)
        if _restricted_projection_required() and "error" not in result:
            return _restricted_warn_projection(result)
        return result
    except Exception as exc:
        return {"error": str(exc)}


def retail_gap_note(
    trade_area: Mapping[str, Any],
    category: str,
) -> dict[str, Any]:
    """Return a directional retail gap note based on explicit conventions."""

    try:
        return _retail_gap_note(trade_area, category)
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "dedupe_listings",
    "employer_warn_events",
    "retail_gap_note",
    "supply_pipeline_signal",
    "trade_area_profile",
]
