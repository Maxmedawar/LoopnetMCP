"""Human location resolver tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.geo.crosswalk import GeoCrosswalk
from cre_mcp.geo.resolver import GeoResolver
from cre_mcp.models import GeoLevel
from tests.conftest import load_fixture


def _resolver(tmp_path, fetch):
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "geo.db",
        hud_api_token=None,
        source_rights_enabled={"geo.census_geocoder": True},
    )
    crosswalk = GeoCrosswalk(config, fetch=fetch, hud_token=None)
    return GeoResolver(
        config,
        fetch=fetch,
        crosswalk=crosswalk,
        cache=SQLiteCache(config.cache_db_path),
    )


@pytest.mark.asyncio
async def test_zip_state_and_county_resolution_are_keyless(tmp_path):
    fetch = AsyncMock()
    resolver = _resolver(tmp_path, fetch)

    zip_geo = await resolver.resolve("78701")
    assert zip_geo.level == GeoLevel.ZIP
    assert zip_geo.county_fips == "48453"
    assert zip_geo.cbsa == "12420"
    assert (await resolver.resolve("TX")).state_fips == "48"
    assert (await resolver.resolve("Travis County, TX")).county_fips == "48453"
    fetch.get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_street_address_degrades_to_city_when_geocoder_misses(tmp_path):
    # A full street address that the Census geocoder can't match must fall back
    # to its city instead of hard-failing (bug: it used the whole street string
    # as the fallback key and raised).
    fetch = AsyncMock()
    fetch.get_json.return_value = {"result": {"addressMatches": []}}
    resolver = _resolver(tmp_path, fetch)

    geo = await resolver.resolve("8600 Cross Park Dr, Austin, TX")

    assert geo.state_fips == "48"
    assert geo.county_fips == "48453"  # Austin -> Travis County via city fallback
    assert geo.level == GeoLevel.CITY


@pytest.mark.asyncio
async def test_census_geocoder_maps_city_county_and_tract(tmp_path):
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("census/geocoder.json"))
    resolver = _resolver(tmp_path, fetch)

    geo = await resolver.resolve("Austin, TX")

    assert geo.level == GeoLevel.CITY
    assert geo.state_fips == "48"
    assert geo.county_fips == "48453"
    assert geo.tract == "48453000700"
    assert "address=Austin%2C+TX" in fetch.get_json.await_args.args[0]
