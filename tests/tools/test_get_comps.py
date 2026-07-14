"""Free comps MCP tool serialization, honesty labels, and registration."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.models import (
    CompsProviderResult,
    Deal,
    GeoLevel,
    GeoRef,
    Listing,
    SaleComp,
    ValueEstimate,
)
from cre_mcp.server import mcp
from cre_mcp.tools.market_tools import get_comps


def _listing() -> Listing:
    return Listing(
        source="crexi",
        source_id="123",
        name="Retail subject",
        address="100 Main St",
        city="Austin",
        state="TX",
        property_type="retail",
        price_usd=1_100_000,
        size_sqft_num=10_000,
        url="https://www.crexi.com/properties/123/example",
    )


def _estimate(method="county_comps", confidence=0.75) -> ValueEstimate:
    return ValueEstimate(
        value=1_000_000,
        low=900_000,
        mid=1_000_000,
        high=1_100_000,
        method=method,
        n_comps=3 if method == "county_comps" else 0,
        confidence=confidence,
        error_band=0.10,
        source="County-limited fixture estimate.",
    )


def _comp() -> SaleComp:
    return SaleComp(
        source="Fixture County",
        county_fips="37081",
        parcel_id="1",
        sale_price=900_000,
        sale_date="2025-01-01",
        sqft=10_000,
    )


@pytest.mark.asyncio
async def test_get_comps_returns_estimate_comps_and_plain_english_position():
    deal = Deal(
        listing=_listing(),
        value_estimate=_estimate(),
        sale_comps=[
            _comp(),
            _comp().model_copy(update={"parcel_id": "2"}),
            _comp().model_copy(update={"parcel_id": "3"}),
        ],
    )
    with (
        patch(
            "cre_mcp.tools.market_tools.analyze_deal",
            new=AsyncMock(return_value=deal.model_dump(mode="json")),
        ),
        patch("cre_mcp.tools.market_tools._paid_comps_providers") as paid,
    ):
        result = await get_comps("123", source="crexi")

    assert "error" not in result
    assert result["value_estimate"]["method"] == "county_comps"
    assert result["value_provenance"] == {
        "method": "county_comps",
        "confidence": 0.75,
        "n_comps": 3,
    }
    assert result["comps"][0]["parcel_id"] == "1"
    assert "10.0% above" in result["explanation"]
    assert "county-fragmented" in result["coverage_note"]
    paid.assert_not_called()


@pytest.mark.asyncio
async def test_address_path_surfaces_labeled_weak_fallback():
    with patch(
        "cre_mcp.tools.market_tools._address_comps",
        new=AsyncMock(return_value=(_listing(), _estimate("fhfa_trend", 0.35), [])),
    ):
        result = await get_comps("100 Main St, Austin, TX 78701")

    assert result["value_estimate"]["method"] == "fhfa_trend"
    assert result["value_estimate"]["confidence"] == 0.35
    assert result["value_provenance"]["n_comps"] == 0
    assert "Method: fhfa_trend" in result["explanation"]


@pytest.mark.asyncio
async def test_get_comps_returns_error_dict_from_analysis_failure():
    with patch(
        "cre_mcp.tools.market_tools.analyze_deal",
        new=AsyncMock(return_value={"error": "unknown source"}),
    ):
        assert await get_comps("bad") == {"error": "unknown source"}


@pytest.mark.asyncio
async def test_get_comps_falls_to_paid_only_when_free_coverage_is_weak_and_enabled():
    deal = Deal(
        listing=_listing(),
        value_estimate=_estimate("fhfa_trend", 0.35),
        sale_comps=[],
    )
    provider = Mock()
    provider.get_comps = AsyncMock(
        return_value=CompsProviderResult(
            provider="attom",
            comps=[_comp()],
            value_estimate=_estimate("attom", 0.82),
        )
    )
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )
    with (
        patch(
            "cre_mcp.tools.market_tools.analyze_deal",
            new=AsyncMock(return_value=deal.model_dump(mode="json")),
        ),
        patch(
            "cre_mcp.tools.market_tools._paid_comps_providers",
            return_value=[provider],
        ),
        patch(
            "cre_mcp.tools.market_tools.resolve",
            new=AsyncMock(return_value=geo),
        ),
    ):
        result = await get_comps("123", source="crexi")

    assert result["value_estimate"]["method"] == "attom"
    assert result["value_provenance"]["confidence"] == 0.82
    provider.get_comps.assert_awaited_once_with(_listing(), geo)


def test_no_paid_keys_builds_no_provider_and_preserves_free_only_behavior():
    from cre_mcp.tools.market_tools import _paid_comps_providers

    config = CreConfig(
        attom_api_key=None,
        regrid_api_key=None,
        _env_file=None,
    )

    assert _paid_comps_providers(config) == []


@pytest.mark.asyncio
async def test_get_comps_remains_registered_in_the_sixty_seven_tool_suite():
    tools = await mcp.get_tools()
    assert "get_comps" in tools
    assert len(tools) == 67
