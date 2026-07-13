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
    assert fetch.get_json.await_args.args[0].endswith("fmr/data/12420?year=2026")
    assert fetch.get_json.await_args.kwargs["headers"] == {
        "Authorization": "Bearer hud-key"
    }
    assert metric.value == 1902
    assert metric.unit == "USD/month"

