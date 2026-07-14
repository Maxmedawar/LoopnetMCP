"""Census provider request and mapping tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.census import CensusProvider
from cre_mcp.models import GeoLevel, GeoRef
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_acs_url_auth_and_metric_mapping():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("census/acs5_profile.json"))
    provider = CensusProvider(config=CreConfig(census_api_key="census-key"), fetch=fetch)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )

    metrics = await provider.acs5_profile(geo, 2023)

    url = fetch.get_json.await_args.args[0]
    assert url.startswith("https://api.census.gov/data/2023/acs/acs5?")
    assert "for=county%3A453" in url and "in=state%3A48" in url
    assert "key=census-key" in url
    assert metrics["population"].value == 1_330_015
    assert metrics["median_hh_income"].value == 99_611
    assert metrics["median_hh_income"].unit == "USD/year"
    assert metrics["rental_vacancy"].value == pytest.approx(4.64, rel=0.01)


@pytest.mark.asyncio
async def test_building_permits_uses_live_annual_county_file():
    fetch = AsyncMock()
    fetch.get_text.return_value = load_fixture("census/building_permits.txt")
    provider = CensusProvider(config=CreConfig(census_api_key=None), fetch=fetch)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )

    metric = await provider.building_permits(geo, 2024)

    fetch.get_text.assert_awaited_once_with(
        "https://www2.census.gov/econ/bps/County/co2024a.txt"
    )
    assert metric.value == 16_990
    assert metric.as_of == "2024"
    assert "final annual county file" in metric.source
