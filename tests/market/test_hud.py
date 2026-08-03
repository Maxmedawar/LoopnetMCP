"""HUD provider request and mapping tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.hud import HudProvider
from cre_mcp.models import GeoLevel, GeoRef
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_hud_fmr_bearer_url_and_mapping():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("hud/fmr.json"))
    provider = HudProvider(config=CreConfig(hud_api_token="hud-key"), fetch=fetch)
    geo = GeoRef(level=GeoLevel.CBSA, state_fips="48", cbsa="12420", name="Austin MSA")
    metric = await provider.fmr(geo, 2026)
    assert fetch.get_json.await_args.args[0].endswith(
        "fmr/data/METRO12420M12420?year=2026"
    )
    assert fetch.get_json.await_args.kwargs["headers"] == {
        "Authorization": "Bearer hud-key"
    }
    assert metric.value == 1924
    assert metric.unit == "USD/month"


@pytest.mark.asyncio
async def test_hud_fmr_by_bedroom_maps_every_published_tier():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("hud/fmr.json"))
    provider = HudProvider(config=CreConfig(hud_api_token="hud-key"), fetch=fetch)
    geo = GeoRef(level=GeoLevel.CBSA, state_fips="48", cbsa="12420", name="Austin MSA")

    tiers = await provider.fmr_by_bedroom(geo, 2026)

    assert {bedrooms: metric.value for bedrooms, metric in tiers.items()} == {
        0: 1519,
        1: 1635,
        2: 1924,
        3: 2470,
        4: 2840,
    }


@pytest.mark.asyncio
async def test_hud_income_limits_maps_live_fixture():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("hud/income_limits.json"))
    provider = HudProvider(config=CreConfig(hud_api_token="hud-key"), fetch=fetch)
    geo = GeoRef(level=GeoLevel.CBSA, state_fips="48", cbsa="12420", name="Austin MSA")

    metric = await provider.income_limits(geo, 2024)

    assert fetch.get_json.await_args.args[0].endswith(
        "il/data/METRO12420M12420?year=2024"
    )
    assert metric.value == 126_000


def test_hud_county_entity_uses_required_ten_digit_suffix():
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )

    assert HudProvider._geo_id(geo) == "4845399999"
