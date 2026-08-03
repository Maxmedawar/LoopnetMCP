"""Auction.com GraphQL listing source."""

import logging
import re
from typing import Any

from cre_mcp.geo.resolver import STATE_FIPS
from cre_mcp.http.errors import FetchClientError
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://graph.auction.com/graphql"
_SEARCH_SIZE = 100
_STATE_ABBR = {fips: abbreviation for abbreviation, fips in STATE_FIPS.items()}
_SEARCH_QUERY = """
query SearchListings($filters: ListingCompatabilityFilters!) {
  seek_listings_from_filters(filters: $filters) {
    total_count total_pages size current_page
    content {
      ... on Listing {
        listing_id urn listing_status listing_status_group listing_page_path
        formatted_address(format: DOUBLE_LINE)
        listing_configuration { product_type asset_type occupancy_status }
        seller_property {
          street_description municipality country_primary_subdivision
          country_secondary_subdivision postal_code
        }
        valuation { seller_current_value_amount }
        primary_property {
          property_id
          summary {
            total_bedrooms total_bathrooms square_footage lot_size year_built
            valuation structure_type_code structure_type_group
            address { coordinates { lon lat } }
          }
        }
        auction { start_date end_date starting_bid is_online }
        external_information(resolvePolicy: CACHE_ONLY) {
          collateral { summary { estimated low high type } }
        }
      }
    }
  }
}
""".strip()
_DETAIL_QUERY = """
query ListingDetail($listingIds: [ID!]!) {
  listings_batched(filters: { listing_ids: $listingIds }) {
    listing_id urn listing_status listing_status_group
    formatted_address(format: DOUBLE_LINE)
    listing_configuration { product_type asset_type occupancy_status }
    seller_property {
      street_description municipality country_primary_subdivision
      country_secondary_subdivision postal_code
    }
    valuation { seller_current_value_amount }
    primary_property {
      property_id
      summary {
        total_bedrooms total_bathrooms square_footage lot_size year_built
        valuation structure_type_code structure_type_group
        address { coordinates { lon lat } }
      }
    }
    auction { start_date end_date starting_bid is_online }
    external_information(resolvePolicy: CACHE_ONLY) {
      collateral { summary { estimated low high type } }
    }
  }
}
""".strip()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    match = re.search(r"-?[\d,.]+", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _property_type(summary: dict[str, Any]) -> str:
    text = " ".join(
        str(summary.get(key) or "")
        for key in ("structure_type_code", "structure_type_group")
    ).casefold()
    if "multi" in text or "apartment" in text:
        return "multifamily"
    if any(term in text for term in ("retail", "commercial")):
        return "retail"
    if "land" in text:
        return "land"
    return "special-purpose"


def _distress_type(item: dict[str, Any]) -> str:
    configuration = _mapping(item.get("listing_configuration"))
    joined = " ".join(
        str(value or "")
        for value in (
            configuration.get("asset_type"),
            configuration.get("product_type"),
            item.get("listing_status"),
        )
    ).casefold()
    if "bank_owned" in joined or "bank owned" in joined:
        return "bank_owned"
    if "reo" in joined:
        return "reo"
    if "foreclos" in joined or "trustee" in joined:
        return "foreclosure"
    return "auction"


def _avm(item: dict[str, Any], summary: dict[str, Any]) -> float | None:
    direct = _number(summary.get("valuation"))
    if direct is not None:
        return direct
    valuation = _mapping(item.get("valuation"))
    direct = _number(valuation.get("seller_current_value_amount"))
    if direct is not None:
        return direct
    external = _mapping(item.get("external_information"))
    collateral = _mapping(external.get("collateral"))
    values = collateral.get("summary")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict) and value.get("type") == "composite":
                return _number(value.get("estimated"))
    return None


def map_auction_listing(item: dict[str, Any]) -> Listing:
    """Defensively map a live GraphQL listing projection."""
    seller = _mapping(item.get("seller_property"))
    primary = _mapping(item.get("primary_property"))
    summary = _mapping(primary.get("summary"))
    coordinates = _mapping(_mapping(summary.get("address")).get("coordinates"))
    auction = _mapping(item.get("auction"))
    source_id = str(item.get("listing_id") or item.get("id") or "")
    path = item.get("listing_page_path") or f"/details/{source_id}"
    url = path if str(path).startswith("http") else f"https://www.auction.com{path}"
    address = str(seller.get("street_description") or "").strip().title()
    city = str(seller.get("municipality") or "").strip().title()
    state = str(seller.get("country_primary_subdivision") or "").strip().upper()
    zip_value = seller.get("postal_code")
    zip_code = str(zip_value).strip()[:5] if zip_value not in (None, "") else None
    price = _number(auction.get("starting_bid"))
    size = _number(summary.get("square_footage"))
    avm = _avm(item, summary)
    raw = dict(item)
    raw.update(
        {
            "avm": avm,
            "distress_type": _distress_type(item),
            "auction_start": auction.get("start_date"),
            "auction_end": auction.get("end_date"),
            "occupancy_status": _mapping(item.get("listing_configuration")).get(
                "occupancy_status"
            ),
        }
    )
    return Listing(
        source="auction_com",
        source_id=source_id,
        refs=[ListingRef(source="auction_com", source_id=source_id, url=url)],
        name=address or f"Auction.com listing {source_id}",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        property_type=_property_type(summary),
        property_subtype=str(summary.get("structure_type_code") or "") or None,
        listing_type="for-sale",
        price=f"${price:,.0f}" if price is not None else None,
        size_sqft=f"{size:,.0f} SF" if size is not None else None,
        lot_size=(
            f"{_number(summary.get('lot_size')):g} acres"
            if _number(summary.get("lot_size")) is not None
            else None
        ),
        year_built=(
            str(int(year))
            if (year := _number(summary.get("year_built"))) is not None
            else None
        ),
        url=url,
        price_usd=price,
        size_sqft_num=size,
        year_built_int=(
            int(year) if (year := _number(summary.get("year_built"))) is not None else None
        ),
        lat=_number(coordinates.get("lat")),
        lon=_number(coordinates.get("lon")),
        is_distressed=True,
        distress_type=_distress_type(item),
        raw=raw,
    )


def _state_for(query: SearchQuery) -> str | None:
    if isinstance(query.geo, GeoRef):
        state = _STATE_ABBR.get(query.geo.state_fips)
        if state:
            return state
    match = re.search(r"(?:^|,\s*|\s)([A-Za-z]{2})(?:\s+\d{5})?\s*$", query.location)
    return match.group(1).upper() if match else None


def _location_filters(query: SearchQuery) -> dict[str, str]:
    filters: dict[str, str] = {}
    state = _state_for(query)
    if state:
        filters["property_state"] = state
    geo = query.geo if isinstance(query.geo, GeoRef) else None
    if geo and geo.level == GeoLevel.ZIP and geo.zip:
        filters["property_zip"] = geo.zip
        return filters
    local_name = query.location.rsplit(",", 1)[0].strip()
    zip_match = re.fullmatch(r"\d{5}", query.location.strip())
    if zip_match:
        filters["property_zip"] = zip_match.group(0)
    elif (geo and geo.level == GeoLevel.COUNTY) or local_name.casefold().endswith(
        "county"
    ):
        filters["property_county"] = re.sub(
            r"\s+county$", "", local_name, flags=re.I
        )
    elif "," in query.location and local_name:
        filters["property_city"] = local_name
    return filters


def _matches(listing: Listing, query: SearchQuery) -> bool:
    if query.property_type and listing.property_type != query.property_type.value:
        return False
    if query.price_min is not None and (
        listing.price_usd is None or listing.price_usd < query.price_min
    ):
        return False
    if query.price_max is not None and (
        listing.price_usd is None or listing.price_usd > query.price_max
    ):
        return False
    if query.size_min is not None and (
        listing.size_sqft_num is None or listing.size_sqft_num < query.size_min
    ):
        return False
    if query.size_max is not None and (
        listing.size_sqft_num is None or listing.size_sqft_num > query.size_max
    ):
        return False
    return True


class AuctionComSource(ListingSource):
    """Auction.com source backed by its live GraphQL search projection."""

    name = "auction_com"
    capabilities = SourceCapabilities(
        supports_distressed=True,
        supports_lease=False,
        detail_is_expensive=False,
    )

    def __init__(self, client: FetchClient | None = None):
        self._client = client
        self._seen: dict[str, Listing] = {}

    @property
    def client(self) -> FetchClient:
        return self._client or get_fetch_client()

    async def search(self, query: SearchQuery) -> list[Listing]:
        filters: dict[str, Any] = {
            "listing_type": "active",
            "sort": "auction_date_order",
            "limit": _SEARCH_SIZE,
            "version": 1,
            "offset": (max(query.page, 1) - 1) * _SEARCH_SIZE,
        }
        filters.update(_location_filters(query))
        body = {
            "operationName": "SearchListings",
            "query": _SEARCH_QUERY,
            "variables": {"filters": filters},
        }
        try:
            payload = await self.client.post_json(GRAPHQL_URL, body)
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        data = _mapping(payload.get("data") if isinstance(payload, dict) else None)
        result = _mapping(data.get("seek_listings_from_filters"))
        content = result.get("content")
        if not isinstance(content, list):
            raise SourceError(self.name, "Auction.com response had no content array")
        listings = [
            map_auction_listing(item)
            for item in content
            if isinstance(item, dict)
        ]
        listings = [listing for listing in listings if _matches(listing, query)]
        self._seen.update({listing.source_id: listing for listing in listings})
        return listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        if ref.source != self.name:
            raise SourceError(self.name, f"Auction.com cannot resolve {ref.source!r}")
        if ref.source_id in self._seen:
            return self._seen[ref.source_id]
        body = {
            "operationName": "ListingDetail",
            "query": _DETAIL_QUERY,
            "variables": {"listingIds": [ref.source_id]},
        }
        try:
            payload = await self.client.post_json(GRAPHQL_URL, body)
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        data = _mapping(payload.get("data") if isinstance(payload, dict) else None)
        items = data.get("listings_batched")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise SourceError(self.name, f"Auction.com listing not found: {ref.source_id}")
        listing = map_auction_listing(items[0])
        if ref.url and listing.url.endswith(f"/details/{ref.source_id}"):
            listing.url = ref.url
            listing.refs[0].url = ref.url
        return listing


__all__ = ["AuctionComSource", "GRAPHQL_URL", "map_auction_listing"]
