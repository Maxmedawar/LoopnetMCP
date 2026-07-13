"""End-to-end flagship deal-tool behavior with external boundaries mocked."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.models import (
    AggregatedSearchResult,
    DealAttributes,
    GeoLevel,
    GeoRef,
    Listing,
    MetricValue,
    RentComps,
    SourceCapabilities,
)
from cre_mcp.tools.deal_tools import analyze_deal, find_deals
from tests.scoring.builders import market_pack


def _listing(source_id: str, *, strong: bool = True) -> Listing:
    raw = (
        {
            "strategy": "nnn_retail",
            "tenant_credit_rating": "A",
            "lease_years_remaining": 15,
            "rent_escalation_pct": 3,
            "lease_type": "absolute nnn",
            "guaranty_type": "corporate investment grade",
            "traffic_count": 35_000,
            "population_3mi": 80_000,
            "median_income_3mi": 90_000,
            "visibility": "corner drive-thru",
            "replacement_cost_per_sf": 400,
            "land_value": 900_000,
            "credit_anchors": 4,
            "job_growth_36mo_pct": 7,
            "population_growth_36mo_pct": 4,
            "us_median_hh_income": 75_000,
        }
        if strong
        else {
            "strategy": "nnn_retail",
            "tenant_credit_rating": "BBB",
        }
    )
    return Listing(
        source="loopnet",
        source_id=source_id,
        name=f"Listing {source_id}",
        address=f"{source_id} Congress Ave",
        city="Austin",
        state="TX",
        zip_code="78701",
        property_type="retail",
        listing_type="for-sale",
        price_usd=2_000_000,
        size_sqft_num=8_000,
        noi_usd=150_000 if strong else None,
        cap_rate_pct=7.5 if strong else None,
        url=f"https://www.loopnet.com/Listing/example/{source_id}/",
        raw=raw,
    )


def _market():
    return market_pack(
        {
            "job_growth_5yr": 3.0,
            "pop_growth_5yr": 2.0,
            "median_hh_income": 100_000,
            "treasury_10yr": 4.0,
            "mortgage_rate": 6.5,
        }
    )


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        cbsa="12420",
        name="Travis County, TX",
    )


@pytest.mark.asyncio
async def test_analyze_deal_deep_fetches_underwrites_and_scores():
    source = Mock(capabilities=SourceCapabilities(detail_is_expensive=True))
    source.get_detail = AsyncMock(return_value=_listing("31948105"))
    fake_registry = Mock()
    fake_registry.get.return_value = source
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())
    url = "https://www.loopnet.com/Listing/example/31948105/"

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch("cre_mcp.tools.deal_tools._market_engine", return_value=market_engine):
        result = await analyze_deal(
            url,
            strategy="nnn_retail",
            assumptions={"annual_interest_rate": 0.055},
        )

    assert "error" not in result
    assert result["listing"]["source_id"] == "31948105"
    assert result["underwriting"]["cap_rate"] == 7.5
    assert result["underwriting"]["assumptions_used"]["annual_interest_rate"] == {
        "value": 0.055,
        "source": "override",
    }
    assert result["scores"][0]["strategy"] == "nnn_retail"
    assert result["scores"][0]["explanation"]
    assert result["best_strategy"] == "nnn_retail"
    source.get_detail.assert_awaited_once()
    assert source.get_detail.await_args.args[0].source_id == "31948105"
    market_engine.get_market_pack.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_deal_extracts_asset_id_from_crexi_url():
    detail = _listing("2622985").model_copy(
        update={
            "source": "crexi",
            "url": "https://www.crexi.com/properties/2622985/example",
        }
    )
    source = Mock(capabilities=SourceCapabilities(detail_is_expensive=False))
    source.get_detail = AsyncMock(return_value=detail)
    fake_registry = Mock()
    fake_registry.get.return_value = source
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch("cre_mcp.tools.deal_tools._market_engine", return_value=market_engine):
        result = await analyze_deal(
            "https://www.crexi.com/properties/2622985/example",
            source="crexi",
            strategy="nnn_retail",
        )

    assert "error" not in result
    source.get_detail.assert_awaited_once()
    assert source.get_detail.await_args.args[0].source_id == "2622985"


@pytest.mark.asyncio
async def test_analyze_deal_populates_phase8_attributes_rent_and_signals():
    listing = _listing("phase8").model_copy(
        update={
            "property_type": "multifamily",
            "lat": 30.2182,
            "lon": -97.6833,
            "parking": "80 Spaces (4.0/1,000 SF)",
            "raw": {"in_place_rent_monthly": 1760},
        }
    )
    source = Mock(capabilities=SourceCapabilities(detail_is_expensive=True))
    source.get_detail = AsyncMock(return_value=listing)
    fake_registry = Mock()
    fake_registry.get.return_value = source
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())
    owner_engine = Mock()
    owner_engine.lookup = AsyncMock(return_value=None)
    attribute_engine = Mock()
    attribute_engine.attributes_for_listing = AsyncMock(
        return_value=DealAttributes(
            drive_thru=True,
            parking=listing.parking,
            size_sqft=listing.size_sqft_num,
        )
    )
    traffic = Mock()
    traffic.nearest_aadt = AsyncMock(
        return_value=MetricValue(
            value=51_053,
            unit="vehicles/day",
            as_of="2025",
            source="TX DOT AADT",
        )
    )
    rent_engine = Mock()
    rent_engine.get_rent_comps = AsyncMock(
        return_value=RentComps(
            geo=_geo(),
            market_rent_estimate=MetricValue(
                value=2200,
                unit="USD/month",
                source="Zillow ZORI",
            ),
        )
    )

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch(
        "cre_mcp.tools.deal_tools._market_engine", return_value=market_engine
    ), patch(
        "cre_mcp.tools.deal_tools._owner_engine", return_value=owner_engine
    ), patch(
        "cre_mcp.tools.deal_tools._attribute_engine", return_value=attribute_engine
    ), patch(
        "cre_mcp.tools.deal_tools.TrafficProvider", return_value=traffic
    ), patch(
        "cre_mcp.tools.deal_tools._rent_engine", return_value=rent_engine
    ):
        result = await analyze_deal("phase8", strategy="value_add_multifamily")

    assert "error" not in result
    assert result["attributes"] == {
        "traffic_aadt": 51_053.0,
        "drive_thru": True,
        "parking": "80 Spaces (4.0/1,000 SF)",
        "size_sqft": 8_000.0,
    }
    assert result["rent_comps"]["market_rent_estimate"]["value"] == 2200
    signal = next(
        item
        for item in result["scores"][0]["rubric_result"]["signal_results"]
        if item["key"] == "rent_gap_to_market"
    )
    assert signal["raw_value"] == 20.0


@pytest.mark.asyncio
async def test_find_deals_reuses_one_market_pack_and_scores_low_data():
    high = _listing("high", strong=True)
    low = _listing("low", strong=False)
    fake_registry = Mock()
    fake_registry.search_all = AsyncMock(
        return_value=AggregatedSearchResult(
            query_location="Austin, TX",
            listings=[low, high],
            per_source_counts={"loopnet": 2},
        )
    )
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ) as resolver, patch(
        "cre_mcp.tools.deal_tools._market_engine", return_value=market_engine
    ):
        result = await find_deals("Austin, TX", strategy="nnn_retail")

    assert "error" not in result
    assert result["total_scored"] == 2
    assert [deal["listing"]["source_id"] for deal in result["deals"]] == [
        "high",
        "low",
    ]
    assert result["deals"][1]["scores"][0]["score"] >= 0
    assert (
        result["deals"][1]["scores"][0]["confidence"]
        < result["deals"][0]["scores"][0]["confidence"]
    )
    resolver.assert_awaited_once_with("Austin, TX")
    market_engine.get_market_pack.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_deals_deep_fetches_only_return_limit():
    high = _listing("high", strong=True)
    low = _listing("low", strong=False)
    source = Mock(capabilities=SourceCapabilities(detail_is_expensive=True))
    source.get_detail = AsyncMock(return_value=high)
    fake_registry = Mock()
    fake_registry.search_all = AsyncMock(
        return_value=AggregatedSearchResult(
            query_location="Austin, TX",
            listings=[high, low],
            per_source_counts={"loopnet": 2},
        )
    )
    fake_registry.get.return_value = source
    market_engine = Mock()
    market_engine.get_market_pack = AsyncMock(return_value=_market())

    with patch("cre_mcp.tools.deal_tools.registry", fake_registry), patch(
        "cre_mcp.tools.deal_tools.resolve", new=AsyncMock(return_value=_geo())
    ), patch("cre_mcp.tools.deal_tools._market_engine", return_value=market_engine):
        result = await find_deals(
            "Austin, TX",
            strategy="nnn_retail",
            limit=1,
            deep=True,
        )

    assert result["returned"] == 1
    assert result["deals"][0]["listing"]["source_id"] == "high"
    source.get_detail.assert_awaited_once()
    market_engine.get_market_pack.assert_awaited_once()


@pytest.mark.asyncio
async def test_deal_tools_return_error_dicts():
    with patch(
        "cre_mcp.tools.deal_tools.registry.get",
        side_effect=ValueError("unknown source"),
    ):
        assert await analyze_deal("123", source="bad") == {
            "error": "unknown source"
        }

    assert await find_deals("Austin", strategy="not-a-rubric") == {
        "error": "Unknown strategy: not-a-rubric"
    }
