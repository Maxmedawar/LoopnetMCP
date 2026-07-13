"""Fixture-driven tests for the LoopNet source adapter."""

from unittest.mock import AsyncMock

from cre_mcp.models import ListingRef
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.loopnet.parsers import (
    parse_property_detail,
    parse_search_results,
)
from cre_mcp.sources.loopnet.source import (
    LoopnetSource,
    listing_from_detail,
    listing_from_summary,
    property_detail_from_listing,
    property_summary_from_listing,
)
from tests.conftest import load_fixture


async def test_search_fixture_maps_numeric_fields_and_source_refs():
    client = AsyncMock()
    client.get_text.return_value = load_fixture("search_results.html")
    source = LoopnetSource(client=client)

    listings = await source.search(
        SearchQuery(
            location="Dallas, TX",
            property_type="office",
            price_min=100_000,
        )
    )

    assert len(listings) == 4
    assert listings[0].source == "loopnet"
    assert listings[0].source_id == "12345"
    assert listings[0].price_usd == 4_500_000
    assert listings[0].size_sqft_num == 25_000
    assert listings[0].refs[0].source == "loopnet"
    assert listings[3].units == 22
    assert listings[3].cap_rate_pct == 6.59
    assert listings[0].raw["loopnet_search"] == {
        "total_results": 4,
        "has_next_page": True,
    }
    fetched_url = client.get_text.await_args.args[0]
    assert "/office/" in fetched_url
    assert "min-price=100000" in fetched_url


async def test_get_detail_fixture_maps_numeric_fields():
    client = AsyncMock()
    client.get_text.return_value = load_fixture("property_detail.html")
    source = LoopnetSource(client=client)
    url = "https://www.loopnet.com/Listing/test/31948105/"

    listing = await source.get_detail(
        ListingRef(source="loopnet", source_id="31948105", url=url)
    )

    assert listing.source_id == "31948105"
    assert listing.price_usd == 4_500_000
    assert listing.size_sqft_num == 25_000
    assert listing.year_built_int == 1985
    assert listing.building_class == "A"
    client.get_text.assert_awaited_once_with(url)


def test_legacy_summary_round_trip_is_lossless():
    summary = parse_search_results(load_fixture("search_results.html"))[0]

    round_tripped = property_summary_from_listing(listing_from_summary(summary))

    assert round_tripped == summary


def test_legacy_detail_round_trip_is_lossless():
    url = "https://www.loopnet.com/Listing/test/31948105/"
    detail = parse_property_detail(load_fixture("property_detail.html"), url)

    round_tripped = property_detail_from_listing(listing_from_detail(detail))

    assert round_tripped == detail
