"""ZORI, government-rent, and optional RentCast comparable assembly."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.http.policies import build_gov_policies
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.market.rent_comps import RentCastProvider, RentCompsService, ZoriProvider
from cre_mcp.models import GeoLevel, GeoRef, MetricValue

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.ZIP,
        state_fips="48",
        county_fips="48453",
        cbsa="12420",
        zip="78701",
        name="78701",
    )


def _metric(value: float, source: str) -> MetricValue:
    return MetricValue(value=value, unit="USD/month", as_of="2024", source=source)


@pytest.mark.asyncio
async def test_zori_live_csv_maps_latest_level_and_trailing_trend():
    fetch = AsyncMock()
    fetch.get_text.return_value = (FIXTURES / "zori" / "zip_78701.csv").read_text()
    level, trend = await ZoriProvider(fetch).metrics(_geo(), "78701")

    assert level is not None and level.value == pytest.approx(2898.946767225863)
    assert level.as_of == "2026-05-31"
    assert trend is not None
    expected = 100 * (2898.946767225863 / 2926.724211394873 - 1)
    assert trend.value == pytest.approx(expected)


@pytest.mark.asyncio
async def test_zori_live_metro_csv_maps_city_and_state():
    fetch = AsyncMock()
    fetch.get_text.return_value = (FIXTURES / "zori" / "metro_austin.csv").read_text()
    geo = _geo().model_copy(update={"level": GeoLevel.CITY, "zip": None, "name": "Austin"})

    level, trend = await ZoriProvider(fetch).metrics(geo, "Austin, TX")

    assert level is not None and level.value == pytest.approx(1635.2094124353225)
    assert "metro" in level.source
    assert trend is not None and trend.value < 0


def test_zori_http_policy_is_monthly_and_persistent():
    policy = build_gov_policies()["files.zillowstatic.com"]
    assert policy.persist is True
    assert policy.cache_ttl_seconds == 30 * 24 * 60 * 60


@pytest.mark.asyncio
async def test_free_assembly_combines_zori_acs_and_hud():
    zori = AsyncMock()
    zori.metrics.return_value = (
        _metric(2000, "Zillow ZORI"),
        MetricValue(value=3.5, unit="percent YoY", source="Zillow ZORI"),
    )
    census = AsyncMock()
    census.acs5_profile.return_value = {"median_gross_rent": _metric(1800, "ACS")}
    hud = AsyncMock()
    hud.fmr_by_bedroom.return_value = {2: _metric(1902, "HUD")}
    rentcast = AsyncMock()
    rentcast.available = False
    service = RentCompsService(zori=zori, census=census, hud=hud, rentcast=rentcast)

    result = await service.get_rent_comps("78701", _geo(), bedrooms=2)

    assert (
        result.market_rent_estimate is not None
        and result.market_rent_estimate.value == 1902
    )
    assert result.coverage == {
        "zillow_zori": True,
        "census_acs": True,
        "hud_fmr": True,
        "rentcast": False,
    }
    assert {item.source for item in result.comps} == {
        "Zillow ZORI",
        "Census ACS",
        "HUD FMR",
    }
    rentcast.comparables.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyless_provider_failures_degrade_to_zori():
    zori = AsyncMock()
    zori.metrics.return_value = (_metric(2000, "Zillow ZORI"), None)
    census = AsyncMock()
    census.acs5_profile.side_effect = RuntimeError("Census unavailable")
    hud = AsyncMock()
    hud.fmr_by_bedroom.side_effect = RuntimeError("HUD token missing")
    rentcast = RentCastProvider(config=CreConfig(rentcast_api_key=None), fetch=AsyncMock())
    service = RentCompsService(zori=zori, census=census, hud=hud, rentcast=rentcast)

    result = await service.get_rent_comps("78701", _geo(), bedrooms=2)

    assert (
        result.market_rent_estimate is not None
        and result.market_rent_estimate.value == 2000
    )
    assert result.coverage["zillow_zori"] is True
    assert result.coverage["census_acs"] is False
    assert result.coverage["hud_fmr"] is False
    assert result.coverage["rentcast"] is False


@pytest.mark.asyncio
async def test_rentcast_key_enables_documented_avm_drop_in():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(
        (FIXTURES / "rentcast" / "avm.json").read_text()
    )
    provider = RentCastProvider(
        config=CreConfig(rentcast_api_key="paid-key"),
        fetch=fetch,
    )

    metric, comparables = await provider.comparables(
        "Austin, TX",
        _geo(),
        address="100 Congress Ave, Austin, TX 78701",
        bedrooms=2,
        property_type="Apartment",
    )

    assert metric is not None and metric.value == 2100
    assert [item.rent for item in comparables] == [2050, 2150]
    assert "/v1/avm/rent/long-term?" in fetch.get_json.await_args.args[0]
    assert fetch.get_json.await_args.kwargs["headers"] == {"X-Api-Key": "paid-key"}


@pytest.mark.asyncio
async def test_rentcast_without_key_raises_provider_unavailable_before_network():
    fetch = AsyncMock()
    provider = RentCastProvider(
        config=CreConfig(rentcast_api_key=None),
        fetch=fetch,
    )
    with pytest.raises(ProviderUnavailableError):
        await provider.comparables("78701", _geo())
    fetch.get_json.assert_not_awaited()
