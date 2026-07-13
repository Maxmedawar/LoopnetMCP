"""Tests for the Crexi source and its captured API fixtures."""

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.models import ListingRef, ListingType, PropertyType
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.crexi.mapping import build_search_body, map_asset
from cre_mcp.sources.crexi.source import DETAIL_URL, SEARCH_URL, CrexiSource

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "crexi"


def _fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_build_search_body_maps_verified_crexi_fields():
    body = build_search_body(
        SearchQuery(
            location="Austin, TX",
            property_type=PropertyType.RETAIL,
            listing_type=ListingType.FOR_SALE,
            price_min=1_000_000,
            price_max=5_000_000,
            size_min=5_000,
            size_max=20_000,
            page=2,
        )
    )

    assert body == _fixture("search_request.json")


def test_build_search_body_maps_lease_platform_without_sale_statuses():
    body = build_search_body(
        SearchQuery(
            location="Austin, TX",
            listing_type=ListingType.FOR_LEASE,
        )
    )

    assert body["searchTypes"] == ["Lease"]
    assert "searchAttributes.status" not in body["filters"]


def test_map_captured_search_assets_populates_numeric_fields():
    assets = _fixture("search_response.json")["items"]

    first = map_asset(assets[0])

    assert first.source == "crexi"
    assert first.source_id == "2247699"
    assert first.price_usd == 2_506_400
    assert first.size_sqft_num == 10_500
    assert first.cap_rate_pct == 6
    assert first.noi_usd == 150_384
    assert first.year_built_int == 1984
    assert first.lat == pytest.approx(30.3288571)
    assert first.lon == pytest.approx(-97.6323503)
    assert first.address == "9606 Old Manor Rd"
    assert first.city == "Austin"
    assert first.state == "TX"
    assert first.refs[0].source == "crexi"
    assert first.url.endswith("/2247699/texas-austin-iron")
    assert first.broker_company == "DWG Capital Group"


def test_map_legacy_search_asset_remains_supported():
    asset = _fixture("legacy_search_response.json")["data"][0]

    listing = map_asset(asset)

    assert listing.source_id == "2622976"
    assert listing.price_usd == 950_000
    assert listing.size_sqft_num == 2_000


def test_map_captured_detail_populates_structured_financials():
    listing = map_asset(_fixture("asset_detail.json"))

    assert listing.price == "$2,106,767"
    assert listing.price_usd == 2_106_767
    assert listing.price_per_sqft == "$231.51"
    assert listing.size_sqft == "9,100"
    assert listing.size_sqft_num == 9_100
    assert listing.cap_rate == "6.65%"
    assert listing.cap_rate_pct == pytest.approx(6.65)
    assert listing.noi == "$140,100"
    assert listing.noi_usd == 140_100
    assert listing.units == 1
    assert listing.year_built_int == 2025
    assert listing.stories == 1
    assert listing.lot_size == "2.23 acres"
    assert listing.highlights == [
        "15 Year Absolute NNN Lease",
        "5% Rent Increases Every 5 Years",
    ]


def test_map_asset_tolerates_missing_and_extra_fields(caplog):
    caplog.set_level(logging.DEBUG)

    listing = map_asset({"unexpectedFutureField": {"nested": True}})

    assert listing.source == "crexi"
    assert listing.source_id == "unknown"
    assert listing.name == "Unknown"
    assert listing.address == ""
    assert "unexpectedFutureField" in caplog.text

    universal = map_asset(
        {"documentType": "Sales", "anotherFutureField": [1, 2, 3]}
    )
    assert universal.source_id == "unknown"
    assert universal.name == "Unknown"
    assert "anotherFutureField" in caplog.text


@pytest.mark.asyncio
async def test_crexi_source_uses_shared_client_for_search_and_detail():
    client = AsyncMock()
    client.post_json.return_value = _fixture("search_response.json")
    client.get_json.return_value = _fixture("asset_detail.json")
    source = CrexiSource(client=client)
    query = SearchQuery(location="Austin, TX", property_type=PropertyType.RETAIL)

    listings = await source.search(query)
    detail = await source.get_detail(
        ListingRef(source="crexi", source_id="2622985")
    )

    assert len(listings) == 1
    client.post_json.assert_awaited_once_with(SEARCH_URL, build_search_body(query))
    client.get_json.assert_awaited_once_with(
        DETAIL_URL.format(source_id="2622985")
    )
    assert detail.cap_rate_pct == pytest.approx(6.65)


@pytest.mark.asyncio
async def test_crexi_source_excludes_missing_numeric_values_when_filtered():
    payload = _fixture("search_response.json")
    missing_price = dict(payload["items"][0])
    missing_price["id"] = "sales-no-price"
    missing_price["propertyPrice"] = {}
    payload["items"] = [payload["items"][0], missing_price]
    client = AsyncMock()
    client.post_json.return_value = payload
    source = CrexiSource(client=client)

    listings = await source.search(
        SearchQuery(location="Austin, TX", price_min=1_000_000)
    )

    assert [listing.source_id for listing in listings] == ["2247699"]
