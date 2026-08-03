"""Plain site-intelligence callables for later FastMCP registration.

This module deliberately has no FastMCP imports, decorators, or registration
side effects.  Each function contains implementation errors at the repository's
stable ``{"error": ...}`` boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.siteintel.dedup import dedupe_listings as _dedupe_listings
from cre_mcp.siteintel.employers import employer_events as _employer_events
from cre_mcp.siteintel.leakage import retail_gap_note as _retail_gap_note
from cre_mcp.siteintel.supply import supply_pipeline as _supply_pipeline
from cre_mcp.siteintel.tradearea import trade_area as _trade_area


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
        return await _employer_events(state, since)
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
