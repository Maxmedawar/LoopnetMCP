"""Flagship deep-analysis and ranked deal-finding tools."""

import logging
import re
from typing import Any

from cre_mcp.enrichment.attributes import (
    AttributeEnricher,
    drive_thru_from_text,
    parking_from_listing,
)
from cre_mcp.enrichment.owner import OwnerLookup
from cre_mcp.enrichment.traffic import TrafficProvider
from cre_mcp.geo.resolver import resolve
from cre_mcp.market.intel import MarketIntel
from cre_mcp.market.rent_comps import RentCompsService
from cre_mcp.models import (
    Deal,
    DealAttributes,
    DealContext,
    DealScore,
    GeoRef,
    Listing,
    ListingRef,
    MarketPack,
    OwnerRecord,
    ParcelRecord,
    RentComps,
    UnderwritingResult,
)
from cre_mcp.scoring.engine import score, score_all
from cre_mcp.scoring.rubrics import RUBRIC_REGISTRY
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.loopnet.urls import extract_listing_id, resolve_property_type
from cre_mcp.sources.registry import SourceRegistry
from cre_mcp.underwriting import UnderwritingAssumptions, underwrite_listing

logger = logging.getLogger(__name__)
registry = SourceRegistry()
_market_intel: MarketIntel | None = None
_owner_lookup: OwnerLookup | None = None
_attribute_enricher: AttributeEnricher | None = None
_rent_comps: RentCompsService | None = None


def _market_engine() -> MarketIntel:
    global _market_intel
    if _market_intel is None:
        _market_intel = MarketIntel()
    return _market_intel


def _owner_engine() -> OwnerLookup:
    global _owner_lookup
    if _owner_lookup is None:
        _owner_lookup = OwnerLookup()
    return _owner_lookup


def _attribute_engine() -> AttributeEnricher:
    global _attribute_enricher
    if _attribute_enricher is None:
        _attribute_enricher = AttributeEnricher()
    return _attribute_enricher


def _rent_engine() -> RentCompsService:
    global _rent_comps
    if _rent_comps is None:
        _rent_comps = RentCompsService()
    return _rent_comps


def _location_for_listing(listing: Listing) -> str:
    if listing.city and listing.state:
        return f"{listing.city}, {listing.state}"
    if listing.zip_code:
        return listing.zip_code
    if listing.state:
        return listing.state
    return listing.address


async def _market_for(
    location: str,
) -> tuple[MarketPack | None, str | None]:
    try:
        geo = await resolve(location)
    except Exception as exc:
        logger.warning("Market intelligence unavailable for %s: %s", location, exc)
        return None, str(exc)
    try:
        return await _market_engine().get_market_pack(geo), None
    except Exception as exc:
        logger.warning("Market intelligence unavailable for %s: %s", location, exc)
        return None, str(exc)


def _geo_from_listing(listing: Listing) -> GeoRef | None:
    county_fips = listing.raw.get("county_fips")
    if county_fips is None and listing.source == "county":
        county_fips = listing.source_id.partition(":")[0]
    fips = str(county_fips or "")
    if not re.fullmatch(r"\d{5}", fips):
        return None
    return GeoRef(
        level="county",
        state_fips=fips[:2],
        county_fips=fips,
        name=f"{listing.city or listing.address}, {listing.state}".strip(", "),
    )


async def _owner_for(
    listing: Listing,
    geo: GeoRef | None,
) -> tuple[OwnerRecord | None, str | None]:
    if geo is None:
        return None, None
    try:
        owner = await _owner_engine().lookup(address=listing.address, geo=geo)
        return owner, None
    except Exception as exc:
        logger.warning("Owner enrichment unavailable for %s: %s", listing.address, exc)
        return None, str(exc)


def _base_attributes(listing: Listing) -> DealAttributes:
    return DealAttributes(
        drive_thru=drive_thru_from_text(listing),
        parking=parking_from_listing(listing),
        size_sqft=listing.size_sqft_num,
    )


async def _attributes_for(
    listing: Listing,
    parcel: ParcelRecord | None = None,
) -> tuple[DealAttributes, dict[str, str]]:
    warnings: dict[str, str] = {}
    lookup_listing = listing
    if (
        (listing.lat is None or listing.lon is None)
        and parcel is not None
        and parcel.lat is not None
        and parcel.lon is not None
    ):
        lookup_listing = listing.model_copy(
            update={"lat": parcel.lat, "lon": parcel.lon}
        )
    try:
        attributes = await _attribute_engine().attributes_for_listing(lookup_listing)
    except Exception as exc:
        logger.warning("Property attributes unavailable for %s: %s", listing.address, exc)
        attributes = _base_attributes(listing)
        warnings["attributes"] = str(exc)
    if (
        lookup_listing.lat is not None
        and lookup_listing.lon is not None
        and listing.state
    ):
        try:
            traffic = await TrafficProvider(listing.state).nearest_aadt(
                lookup_listing.lat,
                lookup_listing.lon,
            )
            if traffic is not None:
                attributes.traffic_aadt = traffic.value
        except Exception as exc:
            logger.warning("Traffic enrichment unavailable for %s: %s", listing.address, exc)
            warnings["traffic"] = str(exc)
    return attributes, warnings


def _is_multifamily(listing: Listing, strategy: str | None) -> bool:
    property_type = (listing.property_type or "").casefold()
    return strategy == "value_add_multifamily" or any(
        value in property_type for value in ("multifamily", "multi-family", "apartment")
    )


async def _rent_for(
    listing: Listing,
    geo: GeoRef | None,
    market: MarketPack | None,
    strategy: str | None,
) -> tuple[RentComps | None, str | None]:
    if geo is None or not _is_multifamily(listing, strategy):
        return None, None
    bedrooms_raw = listing.raw.get("bedrooms")
    try:
        bedrooms = int(bedrooms_raw) if bedrooms_raw is not None else None
    except (TypeError, ValueError):
        bedrooms = None
    location = _location_for_listing(listing)
    try:
        return (
            await _rent_engine().get_rent_comps(
                location,
                geo,
                bedrooms=bedrooms,
                property_type=listing.property_type,
                address=listing.address,
                market_pack=market,
            ),
            None,
        )
    except Exception as exc:
        logger.warning("Rent comparables unavailable for %s: %s", listing.address, exc)
        return None, str(exc)


def _assumptions_for(
    listing: Listing,
    market: MarketPack | None,
    overrides: dict[str, Any] | None,
) -> tuple[UnderwritingAssumptions, bool]:
    values = dict(overrides or {})
    used_market_rate = False
    if "annual_interest_rate" not in values and market and market.mortgage_rate:
        rate = market.mortgage_rate.value
        if rate is not None:
            values["annual_interest_rate"] = rate / 100
            used_market_rate = True
    return UnderwritingAssumptions.for_property_type(listing.property_type, values), used_market_rate


def _underwrite(
    listing: Listing,
    market: MarketPack | None,
    overrides: dict[str, Any] | None,
) -> UnderwritingResult:
    assumptions, used_market_rate = _assumptions_for(listing, market, overrides)
    result = underwrite_listing(listing, assumptions)
    for key in overrides or {}:
        if key in result.assumptions_used:
            result.assumptions_used[key]["source"] = "override"
    if used_market_rate:
        result.assumptions_used["annual_interest_rate"]["source"] = "market"
    return result


def _scores(ctx: DealContext, strategy: str | None) -> list[DealScore]:
    if strategy is None:
        return score_all(ctx)
    try:
        rubric = RUBRIC_REGISTRY[strategy]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {strategy}") from exc
    return [score(ctx, rubric)]


def _deal(
    listing: Listing,
    market: MarketPack | None,
    strategy: str | None,
    assumptions: dict[str, Any] | None,
    *,
    parcel: ParcelRecord | None = None,
    owner: OwnerRecord | None = None,
    attributes: DealAttributes | None = None,
    rent_comps: RentComps | None = None,
) -> Deal:
    underwriting = _underwrite(listing, market, assumptions)
    context = DealContext(
        listing=listing,
        market=market,
        parcel=parcel,
        attributes=attributes or _base_attributes(listing),
        rent_comps=rent_comps,
        underwriting=underwriting,
    )
    scores = _scores(context, strategy)
    return Deal(
        listing=listing,
        market_pack=market,
        parcel=parcel,
        owner=owner,
        attributes=context.attributes,
        rent_comps=rent_comps,
        underwriting=underwriting,
        scores=scores,
        best_strategy=scores[0].strategy if scores else None,
    )


def _listing_ref(listing: Listing) -> ListingRef:
    for ref in listing.refs:
        if ref.source == listing.source:
            return ref
    return ListingRef(
        source=listing.source,
        source_id=listing.source_id,
        url=listing.url,
    )


def _input_ref(url_or_id: str, source: str) -> ListingRef:
    is_url = url_or_id.startswith(("http://", "https://"))
    source_id = url_or_id
    if is_url and source == "loopnet":
        source_id = extract_listing_id(url_or_id) or url_or_id
    elif is_url and source == "crexi":
        match = re.search(r"/(?:lease/)?properties/([^/?#]+)", url_or_id)
        source_id = match.group(1) if match else url_or_id
    elif is_url and source == "auction_com":
        match = re.search(r"-(\d+)(?:[/?#]|$)", url_or_id)
        source_id = match.group(1) if match else url_or_id
    elif is_url and source == "hud_reo":
        match = re.search(r"[?&]case=([^&#]+)", url_or_id)
        source_id = match.group(1) if match else url_or_id
    return ListingRef(
        source=source,
        source_id=source_id,
        url=url_or_id if is_url else None,
    )


def _best_score(deal: Deal) -> float:
    return deal.scores[0].score if deal.scores else 0.0


async def analyze_deal(
    url_or_id: str,
    source: str = "loopnet",
    strategy: str | None = None,
    assumptions: dict[str, Any] | None = None,
) -> dict:
    """Deep-fetch, underwrite, and score one commercial real-estate listing.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered source name. Defaults to LoopNet.
        strategy: Optional rubric name; omit to score all applicable strategies.
        assumptions: Optional underwriting assumption overrides.

    Returns:
        A full Deal including listing, market data, underwriting, scores, and explanations.
    """
    logger.info("analyze_deal called: source=%s listing=%s", source, url_or_id)
    try:
        listing_source = registry.get(source)
        ref = _input_ref(url_or_id, source)
        listing = await listing_source.get_detail(ref)
        location = _location_for_listing(listing)
        market, market_error = await _market_for(location)
        geo = _geo_from_listing(listing)
        if geo is None:
            try:
                geo = await resolve(location)
            except Exception as exc:
                logger.warning("Owner geography unavailable for %s: %s", location, exc)
        owner, owner_error = await _owner_for(listing, geo)
        parcel = owner.parcels[0] if owner and owner.parcels else None
        attributes, attribute_warnings = await _attributes_for(listing, parcel)
        rent_comps, rent_error = await _rent_for(listing, geo, market, strategy)
        deal = _deal(
            listing,
            market,
            strategy,
            assumptions,
            parcel=parcel,
            owner=owner,
            attributes=attributes,
            rent_comps=rent_comps,
        )
        payload = deal.model_dump(mode="json")
        warnings = {}
        if market_error:
            warnings["market"] = market_error
        if owner_error:
            warnings["owner"] = owner_error
        warnings.update(attribute_warnings)
        if rent_error:
            warnings["rent_comps"] = rent_error
        if warnings:
            payload["warnings"] = warnings
        return payload
    except Exception as exc:
        logger.error("analyze_deal error: %s", exc)
        return {"error": str(exc)}


async def find_deals(
    location: str,
    strategy: str | None = None,
    property_type: str | None = None,
    listing_type: str = "for-sale",
    price_min: int | None = None,
    price_max: int | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    sources: list[str] = ["loopnet"],
    min_score: float | None = None,
    limit: int = 25,
    deep: bool = False,
) -> dict:
    """Search, score, filter, and rank listings by Medawar Deal Score.

    Args:
        location: Market location accepted by listing sources and the geo resolver.
        strategy: Optional rubric name; omit for property-type routing.
        property_type: Optional listing property type.
        listing_type: Listing platform, normally 'for-sale' or 'for-lease'.
        price_min: Minimum asking price.
        price_max: Maximum asking price.
        size_min: Minimum building size in square feet.
        size_max: Maximum building size in square feet.
        sources: Listing sources to search. Defaults to LoopNet.
        min_score: Optional minimum Medawar Deal Score.
        limit: Maximum ranked deals returned.
        deep: Deep-fetch and rescore the initially highest-ranked deals.

    Returns:
        Ranked Deals with explanations, shared market provenance, and isolated errors.
    """
    logger.info(
        "find_deals called: location=%s strategy=%s sources=%s deep=%s",
        location,
        strategy,
        sources,
        deep,
    )
    if limit <= 0:
        return {"error": "limit must be greater than zero"}
    if strategy is not None and strategy not in RUBRIC_REGISTRY:
        return {"error": f"Unknown strategy: {strategy}"}
    try:
        query = SearchQuery(
            location=location,
            property_type=resolve_property_type(property_type),
            listing_type=listing_type,
            price_min=price_min,
            price_max=price_max,
            size_min=size_min,
            size_max=size_max,
        )
        aggregated = await registry.search_all(query, sources=sources)
        market, market_error = await _market_for(location)
        errors = dict(aggregated.errors)
        if market_error:
            errors["market"] = market_error

        deals = [
            _deal(listing, market, strategy, assumptions=None)
            for listing in aggregated.listings
        ]
        total_scored = len(deals)
        deals.sort(key=_best_score, reverse=True)
        if min_score is not None:
            deals = [deal for deal in deals if _best_score(deal) >= min_score]

        if deep:
            deepened: list[Deal] = []
            for deal in deals[:limit]:
                listing = deal.listing
                try:
                    listing_source = registry.get(listing.source)
                    detail = await listing_source.get_detail(_listing_ref(listing))
                    deepened.append(_deal(detail, market, strategy, assumptions=None))
                except Exception as exc:
                    key = f"detail:{listing.source}:{listing.source_id}"
                    errors[key] = str(exc)
                    deepened.append(deal)
            deals = deepened + deals[limit:]
            deals.sort(key=_best_score, reverse=True)
            if min_score is not None:
                deals = [deal for deal in deals if _best_score(deal) >= min_score]

        selected = deals[:limit]
        return {
            "query_location": location,
            "strategy": strategy,
            "deals": [deal.model_dump(mode="json") for deal in selected],
            "total_scored": total_scored,
            "returned": len(selected),
            "errors": errors,
            "per_source_counts": aggregated.per_source_counts,
            "deduped": aggregated.deduped,
        }
    except Exception as exc:
        logger.error("find_deals error: %s", exc)
        return {"error": str(exc)}


def _distressed_score(deal: Deal) -> float:
    return next(
        (item.score for item in deal.scores if item.strategy == "distressed"),
        0.0,
    )


async def find_distressed(
    location: str,
    property_type: str | None = None,
    distress_types: list[str] | None = None,
    min_score: float | None = None,
    limit: int = 25,
) -> dict:
    """Find and rank distressed, foreclosure, REO, and tax-sale inventory.

    Args:
        location: Market, state, ZIP, or configured county to search.
        property_type: Optional commercial property-type filter.
        distress_types: Optional subset of auction, foreclosure, reo, bank_owned,
            or tax_sale.
        min_score: Optional minimum NDE distressed score.
        limit: Maximum ranked deals returned.

    Returns:
        Ranked Deals with distressed and asset-rubric scores plus isolated errors.
    """
    logger.info(
        "find_distressed called: location=%s types=%s",
        location,
        distress_types,
    )
    if limit <= 0:
        return {"error": "limit must be greater than zero"}
    allowed_types = {"auction", "foreclosure", "reo", "bank_owned", "tax_sale"}
    requested_types = (
        {value.casefold() for value in distress_types}
        if distress_types is not None
        else None
    )
    if requested_types is not None and not requested_types <= allowed_types:
        invalid = sorted(requested_types - allowed_types)
        return {"error": f"Unknown distress type(s): {', '.join(invalid)}"}
    try:
        try:
            geo = await resolve(location)
        except Exception as exc:
            logger.warning(
                "Distressed query geo resolution unavailable for %s: %s",
                location,
                exc,
            )
            geo = None
        query = SearchQuery(
            location=location,
            geo=geo,
            property_type=resolve_property_type(property_type),
            listing_type="for-sale",
            distressed_only=True,
        )
        distressed_sources = ["hud_reo", "auction_com", "county"]
        aggregated = await registry.search_all(query, sources=distressed_sources)
        listings = [
            listing
            for listing in aggregated.listings
            if listing.is_distressed
            and (
                requested_types is None
                or (listing.distress_type or "").casefold() in requested_types
            )
        ]
        market, market_error = await _market_for(location)
        errors = dict(aggregated.errors)
        if market_error:
            errors["market"] = market_error
        deals = [
            _deal(listing, market, None, assumptions=None)
            for listing in listings
        ]
        total_scored = len(deals)
        deals.sort(key=_distressed_score, reverse=True)
        if min_score is not None:
            deals = [deal for deal in deals if _distressed_score(deal) >= min_score]
        selected = deals[:limit]
        return {
            "query_location": location,
            "strategy": "distressed",
            "deals": [deal.model_dump(mode="json") for deal in selected],
            "total_scored": total_scored,
            "returned": len(selected),
            "errors": errors,
            "per_source_counts": aggregated.per_source_counts,
            "deduped": aggregated.deduped,
        }
    except Exception as exc:
        logger.error("find_distressed error: %s", exc)
        return {"error": str(exc)}
