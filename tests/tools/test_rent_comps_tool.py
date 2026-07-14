"""Rent-comparable MCP tool boundary and registration."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.models import GeoLevel, GeoRef, MetricValue, RentComps
from cre_mcp.server import mcp
from cre_mcp.tools.market_tools import get_rent_comparables


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.ZIP,
        state_fips="48",
        county_fips="48453",
        zip="78701",
        name="78701",
    )


@pytest.mark.asyncio
async def test_get_rent_comparables_returns_serialized_pack():
    geo = _geo()
    engine = Mock()
    engine.get_rent_comps = AsyncMock(
        return_value=RentComps(
            geo=geo,
            market_rent_estimate=MetricValue(
                value=1902,
                unit="USD/month",
                as_of="2026",
                source="HUD FMR",
            ),
            coverage={"zillow_zori": True},
        )
    )
    with patch(
        "cre_mcp.tools.market_tools.resolve", new=AsyncMock(return_value=geo)
    ), patch("cre_mcp.tools.market_tools._rent_engine", return_value=engine):
        result = await get_rent_comparables("78701", bedrooms=2)

    assert result["market_rent_estimate"]["value"] == 1902
    assert result["coverage"] == {"zillow_zori": True}
    engine.get_rent_comps.assert_awaited_once()


@pytest.mark.asyncio
async def test_rent_comps_tool_validation_and_error_dict():
    assert await get_rent_comparables("78701", bedrooms=-1) == {
        "error": "bedrooms must be zero or greater"
    }
    with patch(
        "cre_mcp.tools.market_tools.resolve",
        new=AsyncMock(side_effect=ValueError("unknown location")),
    ):
        assert await get_rent_comparables("?") == {"error": "unknown location"}


@pytest.mark.asyncio
async def test_get_rent_comparables_is_registered_with_execution_tools():
    tools = await mcp.get_tools()
    assert "get_rent_comparables" in tools
    assert len(tools) == 67
