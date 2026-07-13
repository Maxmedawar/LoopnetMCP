"""LoopNet implementation of the listing-source interface."""

import re

from cre_mcp.http.errors import (
    FetchBlockedError,
    FetchClientError,
    FetchRateLimitError,
)
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models import (
    Listing,
    ListingRef,
    PropertyDetail,
    PropertySummary,
    SourceCapabilities,
)
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.loopnet.parsers import (
    parse_cap_rate,
    parse_pagination,
    parse_price,
    parse_property_detail,
    parse_search_results,
    parse_size,
    parse_total_results,
)
from cre_mcp.sources.loopnet.urls import (
    build_detail_url,
    build_search_url,
    extract_listing_id,
)


def _source_id_from_url(url: str) -> str:
    match = re.search(r"/(?:listing|property)/(\d[\d-]*)/", url, re.IGNORECASE)
    return (match.group(1) if match else extract_listing_id(url)) or url


def _year_as_int(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.search(r"\b(\d{4})\b", raw)
    return int(match.group(1)) if match else None


def listing_from_summary(summary: PropertySummary) -> Listing:
    """Map a legacy LoopNet search summary into a unified listing."""
    source_id = _source_id_from_url(summary.url)
    return Listing(
        source="loopnet",
        source_id=source_id,
        refs=[ListingRef(source="loopnet", source_id=source_id, url=summary.url)],
        name=summary.name,
        address=summary.address,
        city=summary.city,
        state=summary.state,
        zip_code=summary.zip_code,
        property_type=summary.property_type,
        listing_type=summary.listing_type,
        price=summary.price,
        price_per_sqft=summary.price_per_sqft,
        cap_rate=summary.cap_rate,
        size_sqft=summary.size_sqft,
        lot_size=summary.lot_size,
        units=summary.units,
        image_url=summary.image_url,
        broker_name=summary.broker_name,
        broker_company=summary.broker_company,
        url=summary.url,
        price_usd=parse_price(summary.price),
        size_sqft_num=parse_size(summary.size_sqft),
        cap_rate_pct=parse_cap_rate(summary.cap_rate),
        raw={"loopnet": summary.model_dump()},
    )


def listing_from_detail(
    detail: PropertyDetail,
    source_id: str | None = None,
) -> Listing:
    """Map a legacy LoopNet detail model into a unified listing."""
    source_id = source_id or _source_id_from_url(detail.url)
    return Listing(
        source="loopnet",
        source_id=source_id,
        refs=[ListingRef(source="loopnet", source_id=source_id, url=detail.url)],
        name=detail.name,
        address=detail.address,
        city=detail.city,
        state=detail.state,
        zip_code=detail.zip_code,
        property_type=detail.property_type,
        property_subtype=detail.property_subtype,
        listing_type=detail.listing_type,
        price=detail.price,
        price_per_sqft=detail.price_per_sqft,
        cap_rate=detail.cap_rate,
        noi=detail.noi,
        size_sqft=detail.size_sqft,
        lot_size=detail.lot_size,
        year_built=detail.year_built,
        building_class=detail.building_class,
        zoning=detail.zoning,
        parking=detail.parking,
        stories=detail.stories,
        units=detail.units,
        description=detail.description,
        highlights=detail.highlights,
        images=detail.images,
        broker_name=detail.broker_name,
        broker_company=detail.broker_company,
        broker_phone=detail.broker_phone,
        url=detail.url,
        last_updated=detail.last_updated,
        price_usd=parse_price(detail.price),
        size_sqft_num=parse_size(detail.size_sqft),
        cap_rate_pct=parse_cap_rate(detail.cap_rate),
        noi_usd=parse_price(detail.noi),
        year_built_int=_year_as_int(detail.year_built),
        raw={"loopnet": detail.model_dump()},
    )


def property_summary_from_listing(listing: Listing) -> PropertySummary:
    """Map a unified listing back to the legacy search shape."""
    return PropertySummary(
        name=listing.name,
        address=listing.address,
        city=listing.city,
        state=listing.state,
        zip_code=listing.zip_code,
        property_type=listing.property_type,
        listing_type=listing.listing_type,
        price=listing.price,
        price_per_sqft=listing.price_per_sqft,
        size_sqft=listing.size_sqft,
        lot_size=listing.lot_size,
        units=listing.units,
        cap_rate=listing.cap_rate,
        url=listing.url,
        image_url=listing.image_url or (listing.images[0] if listing.images else None),
        broker_name=listing.broker_name,
        broker_company=listing.broker_company,
    )


def property_detail_from_listing(listing: Listing) -> PropertyDetail:
    """Map a unified listing back to the legacy detail shape."""
    return PropertyDetail(
        name=listing.name,
        address=listing.address,
        city=listing.city,
        state=listing.state,
        zip_code=listing.zip_code,
        property_type=listing.property_type,
        property_subtype=listing.property_subtype,
        listing_type=listing.listing_type,
        price=listing.price,
        price_per_sqft=listing.price_per_sqft,
        cap_rate=listing.cap_rate,
        noi=listing.noi,
        size_sqft=listing.size_sqft,
        lot_size=listing.lot_size,
        year_built=listing.year_built,
        building_class=listing.building_class,
        zoning=listing.zoning,
        parking=listing.parking,
        stories=listing.stories,
        units=listing.units,
        description=listing.description,
        highlights=listing.highlights,
        images=listing.images,
        broker_name=listing.broker_name,
        broker_company=listing.broker_company,
        broker_phone=listing.broker_phone,
        url=listing.url,
        last_updated=listing.last_updated,
    )


def _retryable(exc: FetchClientError) -> bool:
    return isinstance(exc, FetchRateLimitError) or not isinstance(
        exc,
        FetchBlockedError,
    )


class LoopnetSource(ListingSource):
    """LoopNet source backed by the shared policy-driven FetchClient."""

    name = "loopnet"
    capabilities = SourceCapabilities(detail_is_expensive=True)

    def __init__(self, client: FetchClient | None = None):
        self._client = client

    @property
    def client(self) -> FetchClient:
        return self._client or get_fetch_client()

    async def search(self, query: SearchQuery) -> list[Listing]:
        property_type = (
            query.property_type.value if query.property_type is not None else None
        )
        url = build_search_url(
            query.location,
            property_type,
            query.listing_type.value,
            page=query.page,
            price_min=query.price_min,
            price_max=query.price_max,
            price_type=query.price_type,
            size_min=query.size_min,
            size_max=query.size_max,
        )
        try:
            html = await self.client.get_text(url)
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=_retryable(exc)) from exc

        total_results = parse_total_results(html)
        has_next_page = parse_pagination(html)
        listings = [
            listing_from_summary(summary)
            for summary in parse_search_results(html)
        ]
        for listing in listings:
            listing.raw["loopnet_search"] = {
                "total_results": total_results,
                "has_next_page": has_next_page,
            }
        return listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        if ref.source != self.name:
            raise SourceError(
                self.name,
                f"LoopNet source cannot resolve a {ref.source!r} reference",
            )
        url = ref.url or build_detail_url(ref.source_id)
        try:
            html = await self.client.get_text(url)
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=_retryable(exc)) from exc
        detail = parse_property_detail(html, url)
        return listing_from_detail(detail, source_id=ref.source_id)
