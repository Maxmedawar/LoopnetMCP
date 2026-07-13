"""BLS provider request and mapping tests."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.bls import BlsProvider
from cre_mcp.models import GeoLevel, GeoRef
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_laus_body_auth_and_series_mapping():
    fetch = AsyncMock()
    fetch.post_json.return_value = json.loads(load_fixture("bls/laus.json"))
    provider = BlsProvider(config=CreConfig(bls_api_key="bls-key"), fetch=fetch)
    geo = GeoRef(level=GeoLevel.COUNTY, state_fips="48", county_fips="48453", name="Travis")

    with patch.object(provider, "_years", return_value=("2024", "2025")):
        series = await provider.laus_unemployment(geo)

    fetch.post_json.assert_awaited_once_with(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        {
            "seriesid": ["LAUCN484530000000003"],
            "startyear": "2024",
            "endyear": "2025",
            "registrationkey": "bls-key",
        },
    )
    assert series.points[-1] == ("2025-12", 3.1)
    assert all(point[1] >= 0 for point in series.points)


@pytest.mark.asyncio
async def test_qcew_series_mapping_uses_county_id():
    fetch = AsyncMock()
    fetch.post_json.return_value = json.loads(load_fixture("bls/qcew.json"))
    provider = BlsProvider(fetch=fetch)
    geo = GeoRef(level=GeoLevel.COUNTY, state_fips="48", county_fips="48453", name="Travis")
    series = await provider.qcew_employment(geo)
    assert fetch.post_json.await_args.args[1]["seriesid"] == ["ENU4845320510"]
    assert series.points[-1] == ("2025-Q04", 51085.0)

