"""Public response-shape contracts for the three legacy listing tools."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.tools.listing_tools import (
    get_market_overview,
    get_property_details,
    search_properties,
)
from tests.conftest import load_fixture

pytestmark = pytest.mark.usefixtures("legacy_loopnet_runtime")


@pytest.mark.asyncio
async def test_search_properties_top_level_keys():
    with patch(
        "cre_mcp.http.fetch.FetchClient.get_text",
        new_callable=AsyncMock,
        return_value=load_fixture("search_results.html"),
    ):
        result = await search_properties("Dallas, TX")

    assert set(result) == {
        "has_next_page",
        "page",
        "properties",
        "query_listing_type",
        "query_location",
        "query_property_type",
        "total_results",
    }


@pytest.mark.asyncio
async def test_get_property_details_top_level_keys():
    with patch(
        "cre_mcp.http.fetch.FetchClient.get_text",
        new_callable=AsyncMock,
        return_value=load_fixture("property_detail.html"),
    ):
        result = await get_property_details(
            "https://www.loopnet.com/Listing/test/123/"
        )

    assert set(result) == {
        "address",
        "broker_company",
        "broker_name",
        "broker_phone",
        "building_class",
        "cap_rate",
        "city",
        "description",
        "highlights",
        "images",
        "last_updated",
        "listing_type",
        "lot_size",
        "name",
        "noi",
        "parking",
        "price",
        "price_per_sqft",
        "property_subtype",
        "property_type",
        "size_sqft",
        "state",
        "stories",
        "units",
        "url",
        "year_built",
        "zip_code",
        "zoning",
    }


@pytest.mark.asyncio
async def test_get_market_overview_top_level_keys():
    with patch(
        "cre_mcp.http.fetch.FetchClient.get_text",
        new_callable=AsyncMock,
        return_value=load_fixture("search_results.html"),
    ):
        result = await get_market_overview("Dallas, TX")

    assert set(result) == {
        "avg_cap_rate",
        "avg_price",
        "avg_price_per_sqft",
        "avg_size_sqft",
        "listing_types_breakdown",
        "location",
        "price_range",
        "property_subtypes_breakdown",
        "property_type",
        "sample_listings",
        "size_range",
        "total_listings",
    }
