"""MCP boundaries for nearby-brand and co-tenancy enrichment."""

from __future__ import annotations

import asyncio
import logging

from cre_mcp.enrichment.nearby import nearby_brands as _nearby_brands
from cre_mcp.enrichment.nearby import trade_area_anchors as _trade_area_anchors

logger = logging.getLogger(__name__)


async def nearby_brands(
    lat: float,
    lon: float,
    radius_m: int = 800,
    limit: int = 60,
) -> dict:
    """Find branded OSM points of interest near a coordinate.

    Args:
        lat: Subject latitude in decimal degrees.
        lon: Subject longitude in decimal degrees.
        radius_m: Search radius in meters.
        limit: Maximum number of nearby brands to return.

    Returns:
        Nearby brands, result count, and radius, or an error dictionary.
    """
    logger.info(
        "nearby_brands called: lat=%s lon=%s radius_m=%s limit=%s",
        lat,
        lon,
        radius_m,
        limit,
    )
    try:
        results = await asyncio.to_thread(
            _nearby_brands,
            lat,
            lon,
            radius_m,
            limit,
        )
        return {"brands": results, "count": len(results), "radius_m": radius_m}
    except Exception as exc:
        logger.error("nearby_brands error: %s", exc)
        return {"error": str(exc)}


async def trade_area_anchors(
    lat: float,
    lon: float,
    radius_m: int = 800,
    subject_category: str | None = None,
) -> dict:
    """Summarize complementary anchors and competitors around a site.

    Args:
        lat: Subject latitude in decimal degrees.
        lon: Subject longitude in decimal degrees.
        radius_m: Search radius in meters.
        subject_category: Optional category used to identify direct competitors.

    Returns:
        Trade-area anchor summary, or an error dictionary.
    """
    logger.info(
        "trade_area_anchors called: lat=%s lon=%s radius_m=%s category=%s",
        lat,
        lon,
        radius_m,
        subject_category,
    )
    try:
        return await asyncio.to_thread(
            _trade_area_anchors,
            lat,
            lon,
            radius_m,
            subject_category,
        )
    except Exception as exc:
        logger.error("trade_area_anchors error: %s", exc)
        return {"error": str(exc)}


__all__ = ["nearby_brands", "trade_area_anchors"]
