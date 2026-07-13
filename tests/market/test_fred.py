"""FRED provider request and mapping tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.market.fred import FredProvider
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_fred_bearer_url_and_missing_value_mapping():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture("fred/series.json"))
    provider = FredProvider(config=CreConfig(fred_api_key="fred-key"), fetch=fetch)
    series = await provider.series("DGS10")
    assert "series%2Fobservations" not in fetch.get_json.await_args.args[0]
    assert "series_id=DGS10" in fetch.get_json.await_args.args[0]
    assert fetch.get_json.await_args.kwargs["headers"] == {
        "Authorization": "Bearer fred-key"
    }
    assert series.points == [("2026-07-08", 4.15), ("2026-07-10", 4.18)]


@pytest.mark.asyncio
async def test_fred_missing_key_disables_provider_without_network():
    fetch = AsyncMock()
    provider = FredProvider(config=CreConfig(fred_api_key=None), fetch=fetch)
    with pytest.raises(ProviderUnavailableError):
        await provider.series("DGS10")
    fetch.get_json.assert_not_awaited()

