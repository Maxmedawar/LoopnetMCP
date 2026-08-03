import json
from unittest.mock import AsyncMock, Mock

import pytest

from cre_mcp.models import GeoLevel, GeoRef, ListingRef
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.distressed.auctioncom import AuctionComSource, map_auction_listing
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_auctioncom_live_fixture_maps_numeric_distressed_fields():
    client = Mock()
    client.post_json = AsyncMock(
        return_value=json.loads(load_fixture("auctioncom/search_response.json"))
    )
    listings = await AuctionComSource(client).search(SearchQuery(location="TX"))

    assert len(listings) == 2
    assert listings[0].source == "auction_com"
    assert listings[0].is_distressed is True
    assert listings[0].distress_type == "bank_owned"
    assert listings[0].price_usd == 45_000
    assert listings[0].size_sqft_num == 1_680
    assert listings[1].raw["avm"] == 283_454
    body = client.post_json.await_args.args[1]
    assert body["operationName"] == "SearchListings"
    assert body["variables"]["filters"]["property_state"] == "TX"


@pytest.mark.asyncio
async def test_auctioncom_maps_resolved_county_to_live_filter_name():
    client = Mock()
    client.post_json = AsyncMock(
        return_value=json.loads(load_fixture("auctioncom/search_response.json"))
    )
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )
    await AuctionComSource(client).search(
        SearchQuery(location="Travis County, TX", geo=geo)
    )
    filters = client.post_json.await_args.args[1]["variables"]["filters"]
    assert filters["property_state"] == "TX"
    assert filters["property_county"] == "Travis"


def test_auctioncom_mapping_tolerates_missing_optional_fields():
    listing = map_auction_listing({"listing_id": "missing-fields"})
    assert listing.source_id == "missing-fields"
    assert listing.price_usd is None
    assert listing.size_sqft_num is None
    assert listing.is_distressed is True
    assert listing.distress_type == "auction"


@pytest.mark.asyncio
async def test_auctioncom_detail_uses_batched_graphql_projection():
    captured = json.loads(load_fixture("auctioncom/search_response.json"))
    client = Mock()
    client.post_json = AsyncMock(
        return_value={
            "data": {
                "listings_batched": [
                    captured["data"]["seek_listings_from_filters"]["content"][0]
                ]
            }
        }
    )
    listing = await AuctionComSource(client).get_detail(
        ListingRef(source="auction_com", source_id="2118168")
    )
    assert listing.price_usd == 45_000
    assert client.post_json.await_args.args[1]["operationName"] == "ListingDetail"
