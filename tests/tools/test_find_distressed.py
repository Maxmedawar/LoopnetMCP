from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.models import AggregatedSearchResult, GeoLevel, GeoRef, Listing
from cre_mcp.tools.deal_tools import analyze_deal, find_distressed
from cre_mcp.server import mcp


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="37",
        county_fips="37081",
        name="Guilford County, NC",
    )


def _listing(source_id: str = "37081:1") -> Listing:
    return Listing(
        source="county",
        source_id=source_id,
        name="120 Walnut Crossing Dr",
        address="120 Walnut Crossing Dr",
        city="Greensboro",
        state="NC",
        property_type="special-purpose",
        listing_type="for-sale",
        price_usd=160_000,
        size_sqft_num=2_040,
        url="https://example.test/county/1",
        is_distressed=True,
        distress_type="foreclosure",
        raw={"assessed_value": 322_800, "avm": 322_800},
    )


@pytest.mark.asyncio
async def test_find_distressed_searches_only_distressed_sources_and_ranks():
    fake_registry = Mock()
    fake_registry.search_all = AsyncMock(
        return_value=AggregatedSearchResult(
            query_location="Guilford County, NC",
            listings=[_listing()],
            per_source_counts={"hud_reo": 0, "auction_com": 0, "county": 1},
        )
    )
    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch(
        "cre_mcp.tools.deal_tools._market_for",
        new=AsyncMock(return_value=(None, "offline")),
    ):
        result = await find_distressed(
            "Guilford County, NC",
            distress_types=["foreclosure"],
        )

    assert "error" not in result
    assert result["returned"] == 1
    strategies = {score["strategy"] for score in result["deals"][0]["scores"]}
    assert strategies == {"distressed", "core"}
    assert result["errors"]["market"] == "offline"
    assert fake_registry.search_all.await_args.kwargs["sources"] == [
        "hud_reo",
        "auction_com",
        "county",
    ]
    assert fake_registry.search_all.await_args.args[0].distressed_only is True


@pytest.mark.asyncio
async def test_analyze_distressed_deal_returns_asset_and_distressed_scores():
    source = Mock()
    source.get_detail = AsyncMock(return_value=_listing())
    fake_registry = Mock()
    fake_registry.get.return_value = source
    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools._market_for",
        new=AsyncMock(return_value=(None, None)),
    ):
        result = await analyze_deal("37081:1", source="county")

    assert "error" not in result
    assert {score["strategy"] for score in result["scores"]} == {
        "distressed",
        "core",
    }


@pytest.mark.asyncio
async def test_find_distressed_is_registered_on_server():
    assert "find_distressed" in await mcp.get_tools()


@pytest.mark.asyncio
async def test_find_distressed_validation_returns_error_dicts():
    assert await find_distressed("TX", limit=0) == {
        "error": "limit must be greater than zero"
    }
    assert await find_distressed("TX", distress_types=["unknown"]) == {
        "error": "Unknown distress type(s): unknown"
    }
