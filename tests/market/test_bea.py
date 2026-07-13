"""BEA provider request and mapping tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.bea import BeaProvider
from cre_mcp.models import GeoLevel, GeoRef
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_bea_query_auth_and_regional_mapping():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("bea/regional.json"))
    provider = BeaProvider(config=CreConfig(bea_api_key="bea-key"), fetch=fetch)
    geo = GeoRef(level=GeoLevel.COUNTY, state_fips="48", county_fips="48453", name="Travis")
    series = await provider.regional(geo, "CAGDP1")
    url = fetch.get_json.await_args.args[0]
    assert url.startswith("https://apps.bea.gov/api/data/?")
    assert "datasetname=Regional" in url and "GeoFIPS=48453" in url
    assert "UserID=bea-key" in url
    assert series.points[-1] == ("2023", 201435118.0)

