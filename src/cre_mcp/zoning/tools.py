"""Plain zoning/permit callables for later FastMCP registration by the server."""

from __future__ import annotations

from typing import Any

from cre_mcp.zoning.lookup import zoning_at
from cre_mcp.zoning.permits import permits_near
from cre_mcp.zoning.providers import code_link_for


async def lookup_zoning(
    lat: float,
    lon: float,
    jurisdiction: str | None,
) -> dict[str, Any]:
    """Look up zoning without registering this function as an MCP tool."""

    return await zoning_at(lat, lon, jurisdiction)


async def nearby_permits(
    lat: float,
    lon: float,
    city: str,
    since_days: int = 365,
) -> dict[str, Any]:
    """Look up nearby permits without registering this function as an MCP tool."""

    return await permits_near(lat, lon, city, since_days)


def zoning_code_link(state: str, city: str) -> str | None:
    """Return where humans read the jurisdiction's zoning rules, if wired."""

    return code_link_for(state, city)


__all__ = ["lookup_zoning", "nearby_permits", "zoning_code_link"]
