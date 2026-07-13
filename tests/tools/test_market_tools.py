"""Market tool serialization, ranking, and errors."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.models import GeoLevel, GeoRef, MarketPack, MetricValue
from cre_mcp.tools.market_tools import compare_markets, market_intel


def _pack(name="Austin", growth=2.0):
    metric = MetricValue(value=growth, unit="percent CAGR", as_of="2024", source="fixture")
    income = MetricValue(value=95_000, unit="USD/year", as_of="2024", source="fixture")
    population = MetricValue(value=1_000_000, unit="people", as_of="2024", source="fixture")
    return MarketPack(
        geo=GeoRef(
            level=GeoLevel.COUNTY,
            state_fips="48",
            county_fips="48453",
            name=name,
        ),
        population=population,
        job_growth_5yr=metric,
        pop_growth_5yr=metric,
        median_hh_income=income,
        coverage={
            "population": True,
            "job_growth_5yr": True,
            "pop_growth_5yr": True,
            "median_hh_income": True,
            "net_migration": False,
        },
    )


@pytest.mark.asyncio
async def test_market_intel_has_provenance_score_and_coverage_summary():
    geo = _pack().geo
    engine = AsyncMock()
    engine.get_market_pack.return_value = _pack()
    with patch("cre_mcp.tools.market_tools.resolve", new=AsyncMock(return_value=geo)), patch(
        "cre_mcp.tools.market_tools._engine", return_value=engine
    ):
        result = await market_intel("Austin, TX")

    assert result["population"]["source"] == "fixture"
    assert result["coverage_summary"]["ratio"] == 0.8
    assert result["market_score"] > 0
    assert 0 < result["score_confidence"] < 1


@pytest.mark.asyncio
async def test_market_intel_keyless_partial_pack_does_not_raise():
    pack = _pack()
    engine = AsyncMock()
    engine.get_market_pack.return_value = pack
    with patch(
        "cre_mcp.tools.market_tools.resolve", new=AsyncMock(return_value=pack.geo)
    ), patch("cre_mcp.tools.market_tools._engine", return_value=engine):
        result = await market_intel("Austin, TX")

    assert "error" not in result
    assert 0 < result["coverage_summary"]["ratio"] < 1


@pytest.mark.asyncio
async def test_market_intel_returns_error_dict_on_resolution_failure():
    with patch(
        "cre_mcp.tools.market_tools.resolve",
        new=AsyncMock(side_effect=ValueError("unknown location")),
    ):
        assert await market_intel("?") == {"error": "unknown location"}


@pytest.mark.asyncio
async def test_compare_markets_ranks_and_captures_errors():
    side_effect = [
        {"market_score": 80.0, "geo": {"name": "Austin"}},
        {"error": "unresolved"},
        {"market_score": 90.0, "geo": {"name": "Dallas"}},
    ]
    with patch(
        "cre_mcp.tools.market_tools.market_intel",
        new=AsyncMock(side_effect=side_effect),
    ):
        result = await compare_markets(["Austin", "Bad", "Dallas"])

    assert [market["location"] for market in result["markets"]] == ["Dallas", "Austin"]
    assert [market["rank"] for market in result["markets"]] == [1, 2]
    assert result["errors"] == {"Bad": "unresolved"}


@pytest.mark.asyncio
async def test_market_tools_are_registered_on_server():
    from cre_mcp.server import mcp

    tools = await mcp.get_tools()
    assert {"market_intel", "compare_markets"} <= set(tools)
