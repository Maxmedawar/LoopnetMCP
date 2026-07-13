"""MCP tools for government-backed market intelligence."""

import asyncio
import logging
from typing import Any

from cre_mcp.geo.resolver import resolve
from cre_mcp.market.intel import MarketIntel, market_score
from cre_mcp.market.rent_comps import RentCompsService
from cre_mcp.models.market import MarketPack

logger = logging.getLogger(__name__)
_intel: MarketIntel | None = None
_rent_comps: RentCompsService | None = None


def _engine() -> MarketIntel:
    global _intel
    if _intel is None:
        _intel = MarketIntel()
    return _intel


def _rent_engine() -> RentCompsService:
    global _rent_comps
    if _rent_comps is None:
        _rent_comps = RentCompsService()
    return _rent_comps


def _serialize(pack: MarketPack) -> dict[str, Any]:
    payload = pack.model_dump(mode="json")
    score, confidence = market_score(pack)
    covered = sum(pack.coverage.values())
    total = len(pack.coverage)
    payload.update(
        {
            "market_score": score,
            "score_confidence": confidence,
            "coverage_summary": {
                "covered": covered,
                "total": total,
                "ratio": round(covered / total, 4) if total else 0.0,
                "missing": [name for name, present in pack.coverage.items() if not present],
            },
        }
    )
    return payload


async def market_intel(location: str) -> dict:
    """Get normalized government market fundamentals and a coverage-aware market score.

    Args:
        location: City/state, county/state, state abbreviation, or five-digit ZIP code.

    Returns:
        A partial MarketPack with per-metric provenance, coverage, score, and confidence.
    """
    logger.info("market_intel called: location=%s", location)
    try:
        geo = await resolve(location)
        pack = await _engine().get_market_pack(geo)
        return _serialize(pack)
    except Exception as exc:
        logger.error("market_intel error for %s: %s", location, exc)
        return {"error": str(exc)}


async def compare_markets(locations: list[str]) -> dict:
    """Compare and rank multiple markets by coverage-aware market score.

    Args:
        locations: Two or more city/state, county/state, state, or ZIP locations.

    Returns:
        Ranked market intelligence results plus per-location resolution errors.
    """
    logger.info("compare_markets called: locations=%s", locations)
    if not locations:
        return {"error": "At least one location is required"}
    results = await asyncio.gather(*(market_intel(location) for location in locations))
    markets: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for location, result in zip(locations, results, strict=True):
        if "error" in result:
            errors[location] = str(result["error"])
        else:
            markets.append({"location": location, **result})
    markets.sort(key=lambda item: item["market_score"], reverse=True)
    for rank, market in enumerate(markets, start=1):
        market["rank"] = rank
    return {"markets": markets, "errors": errors, "count": len(markets)}


async def get_rent_comparables(
    location: str,
    bedrooms: int | None = None,
    property_type: str | None = None,
) -> dict:
    """Get free public rent benchmarks and optional paid rental comparables.

    Args:
        location: City/state, county/state, or five-digit ZIP code.
        bedrooms: Optional bedroom count; zero represents a studio.
        property_type: Optional RentCast-compatible residential property type.

    Returns:
        Coverage-aware ZORI, Census ACS, HUD FMR, and optional RentCast data.
    """
    logger.info(
        "get_rent_comparables called: location=%s bedrooms=%s property_type=%s",
        location,
        bedrooms,
        property_type,
    )
    if bedrooms is not None and bedrooms < 0:
        return {"error": "bedrooms must be zero or greater"}
    try:
        geo = await resolve(location)
        comps = await _rent_engine().get_rent_comps(
            location,
            geo,
            bedrooms=bedrooms,
            property_type=property_type,
        )
        return comps.model_dump(mode="json")
    except Exception as exc:
        logger.error("get_rent_comparables error for %s: %s", location, exc)
        return {"error": str(exc)}
