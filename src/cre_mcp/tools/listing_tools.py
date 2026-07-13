"""Legacy LoopNet listing tools."""

import logging
from typing import Optional

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
) -> dict:
    """Search Loopnet for commercial real estate listings by location and filters.

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

    Returns:
        Search results with matching property listings.
    """
    logger.info("search_properties called: location=%s, type=%s", location, property_type)
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
        aggregated = await registry.search_all(query, sources=["loopnet"])
        if aggregated.errors and not aggregated.listings:
            message = aggregated.errors.get("loopnet") or next(
                iter(aggregated.errors.values())
            )
            return {"error": message, "query_location": location, "properties": []}
        properties = [
            property_summary_from_listing(listing)
            for listing in aggregated.listings
        ]
        total, has_next = _loopnet_search_metadata(aggregated.listings)
        result = SearchResult(
            query_location=location,
            query_property_type=property_type,
            query_listing_type=listing_type,
            total_results=total if total is not None else len(properties),
            page=page or 1,
            has_next_page=has_next,
            properties=properties,
        )
        return result.model_dump()
    except SourceError as e:
        logger.error("search_properties error: %s", e)
        return {"error": str(e), "query_location": location, "properties": []}


async def get_property_details(
    url_or_id: str,
) -> dict:
    """Get full details for a specific Loopnet commercial property listing.

    Args:
        url_or_id: Full Loopnet URL (e.g. 'https://www.loopnet.com/Listing/...') or listing ID number.

    Returns:
        Comprehensive property information including price, size, year built, description, broker info, and images.
    """
    logger.info("get_property_details called: %s", url_or_id)
    url = url_or_id if url_or_id.startswith("http") else build_detail_url(url_or_id)
    try:
        source_id = extract_listing_id(url) or url_or_id
        source = registry.get("loopnet")
        listing = await source.get_detail(
            ListingRef(source="loopnet", source_id=source_id, url=url)
        )
        detail = property_detail_from_listing(listing)
        return detail.model_dump()
    except SourceError as e:
        logger.error("get_property_details client error: %s", e)
        return {"error": str(e), "url": url}
    except Exception as e:
        logger.error("get_property_details parse error: %s", e)
        return {"error": f"Failed to parse property page: {e}", "url": url}


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
