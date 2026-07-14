"""MCP tools for government-backed market intelligence."""

import asyncio
import logging
import re
from typing import Any

from cre_mcp.comps.avm import estimate_value
from cre_mcp.comps.records import sale_comps
from cre_mcp.enrichment.counties import config_for_geo
from cre_mcp.enrichment.owner import OwnerLookup
from cre_mcp.geo.resolver import resolve
from cre_mcp.market.intel import MarketIntel, market_score
from cre_mcp.market.rent_comps import RentCompsService
from cre_mcp.models import Deal, Listing, ParcelRecord, SaleComp, ValueEstimate
from cre_mcp.models.market import MarketPack
from cre_mcp.sources.dedupe import normalize_address
from cre_mcp.tools.deal_tools import analyze_deal

logger = logging.getLogger(__name__)
_intel: MarketIntel | None = None
_rent_comps: RentCompsService | None = None
_owner_lookup: OwnerLookup | None = None


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


def _owner_engine() -> OwnerLookup:
    global _owner_lookup
    if _owner_lookup is None:
        _owner_lookup = OwnerLookup()
    return _owner_lookup


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


def _is_address(value: str) -> bool:
    return (
        not value.startswith(("http://", "https://"))
        and bool(re.search(r"\d", value))
        and bool(re.search(r"\s", value))
    )


def _subject_with_parcel(address: str, parcel: ParcelRecord | None) -> Listing:
    config_state = None
    raw: dict[str, Any] = {}
    if parcel:
        if parcel.last_sale_price is not None:
            raw["last_sale_price"] = parcel.last_sale_price
        if parcel.last_sale_date:
            raw["last_sale_date"] = parcel.last_sale_date
    state_match = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b", address.upper())
    if state_match:
        config_state = state_match.group(1)
    return Listing(
        source="address",
        source_id=normalize_address(address) or address,
        name=address,
        address=address,
        city="",
        state=config_state or "",
        property_type=parcel.use_code if parcel else None,
        price_usd=None,
        size_sqft_num=parcel.building_sqft if parcel else None,
        units=int(parcel.units) if parcel and parcel.units else None,
        lat=parcel.lat if parcel else None,
        lon=parcel.lon if parcel else None,
        url="https://address.local/subject",
        raw=raw,
    )


async def _address_comps(
    address: str,
) -> tuple[Listing, ValueEstimate, list[SaleComp]]:
    geo = await resolve(address)
    owner = await _owner_engine().lookup(address=address, geo=geo)
    parcel = owner.parcels[0] if owner and owner.parcels else None
    subject = _subject_with_parcel(address, parcel)
    if not subject.state:
        config = config_for_geo(geo)
        if config:
            subject = subject.model_copy(update={"state": config.state})
    try:
        market = await _engine().get_market_pack(geo)
    except Exception as exc:
        logger.warning("Market context unavailable for comps at %s: %s", address, exc)
        market = None
    try:
        comps = await sale_comps(geo, subject)
    except Exception as exc:
        logger.warning("County sale comps unavailable for %s: %s", address, exc)
        comps = []
    return subject, estimate_value(subject, comps, market), comps


def _comps_explanation(
    subject: Listing,
    estimate: ValueEstimate,
) -> str:
    if estimate.mid is None:
        return (
            "No defensible value range is available. Free closed-sale coverage is county-"
            "fragmented, and no usable FHFA or asking-listing fallback was present."
        )
    ask = subject.price_usd
    comparison = "The subject has no asking price to compare with the modeled midpoint."
    if ask is not None and estimate.mid > 0:
        difference = (ask / estimate.mid - 1) * 100
        position = "above" if difference >= 0 else "below"
        comparison = (
            f"The ${ask:,.0f} ask is {abs(difference):.1f}% {position} the "
            f"${estimate.mid:,.0f} modeled midpoint."
        )
    uncertainty = (
        f" Confidence is {estimate.confidence:.0%} with an approximate "
        f"±{estimate.error_band:.0%} error band."
        if estimate.error_band is not None
        else f" Confidence is {estimate.confidence:.0%}."
    )
    return f"{comparison}{uncertainty} Method: {estimate.method}. {estimate.source}"


async def get_comps(
    url_or_id: str,
    source: str = "loopnet",
) -> dict:
    """Return free county sale comps and an honestly labeled value estimate.

    Args:
        url_or_id: Listing URL/source ID, or a full property address.
        source: Registered listing source when a URL or ID is supplied.

    Returns:
        Value estimate, comps used, confidence/error band, and plain-English context.
    """
    logger.info("get_comps called: source=%s subject=%s", source, url_or_id)
    try:
        if _is_address(url_or_id):
            subject, value_estimate, comps = await _address_comps(url_or_id)
        else:
            payload = await analyze_deal(url_or_id, source=source)
            if "error" in payload:
                return {"error": str(payload["error"])}
            deal = Deal.model_validate(payload)
            subject = deal.listing
            value_estimate = deal.value_estimate or estimate_value(
                subject,
                deal.sale_comps,
                deal.market_pack,
            )
            comps = deal.sale_comps
        return {
            "subject": {
                "source": subject.source,
                "source_id": subject.source_id,
                "address": subject.address,
                "asking_price": subject.price_usd,
            },
            "value_estimate": value_estimate.model_dump(mode="json"),
            "comps": [comp.model_dump(mode="json") for comp in comps],
            "explanation": _comps_explanation(subject, value_estimate),
            "coverage_note": (
                "Free closed-sale data is county-fragmented; county_comps is the strongest "
                "path, while fhfa_trend and listing_context are explicitly weaker fallbacks."
            ),
        }
    except Exception as exc:
        logger.error("get_comps error for %s: %s", url_or_id, exc)
        return {"error": str(exc)}
