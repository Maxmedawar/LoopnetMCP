"""Legacy LoopNet listing tools."""

import logging
from typing import Optional

from cre_mcp.access.context import current_context
from cre_mcp.access.engine import structured_property_within_territories
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.models import Listing, ListingRef, MarketOverview, SearchResult
from cre_mcp.sources.base import SearchQuery, SourceError
from cre_mcp.sources.loopnet.parsers import build_market_overview
from cre_mcp.sources.loopnet.source import (
    property_detail_from_listing,
    property_summary_from_listing,
)
from cre_mcp.sources.loopnet.urls import (
    build_detail_url,
    extract_listing_id,
    resolve_property_type,
)
from cre_mcp.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)
registry = SourceRegistry()


def _restricted_listings(listings: list[Listing]) -> list[Listing]:
    """Validate provider rows before aggregation and remove opaque egress data."""
    ctx = current_context()
    if ctx is None or ctx.trusted or ctx.profile not in TERRITORY_LIMITED:
        return listings
    projected: list[Listing] = []
    for listing in listings:
        payload = listing.model_dump(mode="json")
        if not structured_property_within_territories(payload, ctx.territories):
            raise ValueError("restricted listing result denied")
        projected.append(
            listing.model_copy(update={"lat": None, "lon": None, "raw": {}})
        )
    return projected


def _loopnet_search_metadata(listings: list[Listing]) -> tuple[int | None, bool]:
    for listing in listings:
        metadata = listing.raw.get("loopnet_search")
        if metadata:
            return metadata.get("total_results"), bool(
                metadata.get("has_next_page", False)
            )
    return None, False


async def search_properties(
    location: str,
    property_type: Optional[str] = None,
    listing_type: Optional[str] = "for-sale",
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    price_type: Optional[str] = None,
    size_min: Optional[int] = None,
    size_max: Optional[int] = None,
    page: Optional[int] = None,
    sources: list[str] | None = None,
) -> dict:
    """Search commercial real estate listings by location and filters.

    Args:
        location: City and state (e.g. 'Houston, TX'), state abbreviation ('TX'), or zip code ('77001').
        property_type: Property type: office, retail, industrial, multifamily, land, hospitality, special-purpose, health-care. Synonyms accepted (e.g. 'apartment', 'apartments', 'duplex', 'triplex', 'quadplex', 'multi-family').
        listing_type: Either 'for-sale' or 'for-lease'. Defaults to 'for-sale'.
        price_min: Minimum price filter in dollars.
        price_max: Maximum price filter in dollars.
        price_type: Price basis: 'unit' ($/unit), 'sf' ($/sqft), or 'acre' ($/acre).
        size_min: Minimum size filter in square feet.
        size_max: Maximum size filter in square feet.
        page: Page number (1-indexed). Check has_next_page in the response to know if more pages are available.
        sources: Optional source names such as ['loopnet', 'crexi']. Omit to preserve the legacy LoopNet-only response. When provided, the response contains unified listings plus per_source_counts, errors, and deduped metadata.

    Returns:
        Legacy LoopNet search results when sources is omitted; otherwise a rich unified multi-source result.
    """
    logger.info(
        "search_properties called: location=%s, type=%s, sources=%s",
        location,
        property_type,
        sources,
    )
    try:
        query = SearchQuery(
            location=location,
            property_type=resolve_property_type(property_type),
            listing_type=listing_type or "for-sale",
            page=page or 1,
            price_min=price_min,
            price_max=price_max,
            price_type=price_type,
            size_min=size_min,
            size_max=size_max,
        )
        requested_sources = ["loopnet"] if sources is None else sources
        aggregated = await registry.search_all(query, sources=requested_sources)
        # Pagination metadata lives in provider-only raw fields. Capture it
        # before the restricted projection removes those opaque fields from
        # every client-visible listing.
        legacy_total, legacy_has_next = _loopnet_search_metadata(aggregated.listings)
        restricted_listings = _restricted_listings(aggregated.listings)
        aggregated = aggregated.model_copy(update={"listings": restricted_listings})
        if sources is not None:
            return aggregated.model_dump(mode="json")
        if aggregated.errors and not aggregated.listings:
            message = aggregated.errors.get("loopnet") or next(
                iter(aggregated.errors.values())
            )
            return {"error": message, "query_location": location, "properties": []}
        properties = [
            property_summary_from_listing(listing)
            for listing in aggregated.listings
        ]
        result = SearchResult(
            query_location=location,
            query_property_type=property_type,
            query_listing_type=listing_type,
            total_results=(
                legacy_total if legacy_total is not None else len(properties)
            ),
            page=page or 1,
            has_next_page=legacy_has_next,
            properties=properties,
        )
        return result.model_dump()
    except SourceError as e:
        logger.error("search_properties error: %s", e)
        return {"error": str(e), "query_location": location, "properties": []}


async def get_property_details(
    url_or_id: str,
    source: str | None = None,
) -> dict:
    """Get full details for a specific commercial property listing (LoopNet or Crexi).

    Args:
        url_or_id: A full listing URL (loopnet.com or crexi.com), a bare listing ID,
            or a source-qualified reference such as 'crexi:2335936'.
        source: Optional source name ('loopnet' or 'crexi') for a bare ID. When
            omitted it is inferred from the URL host or a 'source:id' prefix, and
            otherwise defaults to 'loopnet'.

    Returns:
        Comprehensive property information including price, size, year built, description, broker info, and images.
    """
    logger.info("get_property_details called: %s (source=%s)", url_or_id, source)
    raw = url_or_id.strip()
    resolved_source = source.lower() if source else None
    url: str | None = None

    if raw.startswith("http"):
        host = raw.lower()
        if resolved_source is None:
            resolved_source = "crexi" if "crexi.com" in host else "loopnet"
        url = raw
        if resolved_source == "crexi":
            source_id = raw.rstrip("/").split("?")[0].split("/")[-1]
        else:
            source_id = extract_listing_id(raw) or raw
    elif ":" in raw and raw.split(":", 1)[0].lower() in {"loopnet", "crexi"}:
        prefix, source_id = raw.split(":", 1)
        resolved_source = prefix.lower()
    else:
        resolved_source = resolved_source or "loopnet"
        source_id = raw

    if resolved_source == "loopnet" and url is None:
        url = build_detail_url(source_id)

    try:
        src = registry.get(resolved_source)
        listing = await src.get_detail(
            ListingRef(source=resolved_source, source_id=source_id, url=url)
        )
        detail = property_detail_from_listing(listing)
        return detail.model_dump()
    except SourceError as e:
        logger.error("get_property_details client error: %s", e)
        return {"error": str(e), "url": url, "source": resolved_source}
    except Exception as e:
        logger.error("get_property_details parse error: %s", e)
        return {"error": f"Failed to parse property page: {e}", "url": url, "source": resolved_source}


async def get_market_overview(
    location: str,
    property_type: Optional[str] = None,
) -> dict:
    """Get a market overview with aggregate statistics for commercial real estate in a location.

    Args:
        location: City and state (e.g. 'Houston, TX'), state abbreviation ('TX'), or zip code ('77001').
        property_type: Property type: office, retail, industrial, multifamily, land.

    Returns:
        Market statistics including total listings, average price, price per sqft, and breakdowns by type.
    """
    logger.info("get_market_overview called: location=%s, type=%s", location, property_type)
    query = SearchQuery(
        location=location,
        property_type=resolve_property_type(property_type),
    )
    aggregated = await registry.search_all(query, sources=["loopnet"])
    restricted_listings = _restricted_listings(aggregated.listings)
    aggregated = aggregated.model_copy(update={"listings": restricted_listings})
    if aggregated.errors and not aggregated.listings:
        message = aggregated.errors.get("loopnet") or next(
            iter(aggregated.errors.values())
        )
        logger.error("Market overview fetch failed: %s", message)
        return {"error": message, "location": location}
    properties = [
        property_summary_from_listing(listing)
        for listing in aggregated.listings
    ]
    overview = build_market_overview(location, property_type, properties)
    return overview.model_dump()
