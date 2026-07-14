"""Plain async callables for later FastMCP registration by the integration layer."""

from __future__ import annotations

from typing import Any

from cre_mcp.envscreen.hazards import fema_flood_zone, hazard_profile as _hazard_profile
from cre_mcp.envscreen.screen import environmental_screen as _environmental_screen


async def environmental_screen(lat: float, lon: float) -> dict[str, Any]:
    """Return a federal pre-Phase-I environmental screening memo."""
    return await _environmental_screen(lat, lon)


async def flood_zone(lat: float, lon: float) -> dict[str, Any]:
    """Return the FEMA NFHL flood-zone result for a point."""
    return await fema_flood_zone(lat, lon)


async def hazard_profile(lat: float, lon: float) -> dict[str, Any]:
    """Return a qualified flood, wildfire, and seismic hazard profile."""
    return await _hazard_profile(lat, lon)


__all__ = ["environmental_screen", "flood_zone", "hazard_profile"]
