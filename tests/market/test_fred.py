"""FRED provider request and mapping tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.market.fred import FredProvider
from tests.conftest import load_fixture


@pytest.mark.parametrize(
    ("series_id", "fixture", "expected_latest"),
    [
        ("DGS10", "fred/series.json", ("2026-07-10", 4.56)),
        ("MORTGAGE30US", "fred/mortgage30us.json", ("2026-07-09", 6.49)),
        ("SOFR", "fred/sofr.json", ("2026-07-10", 3.55)),
    ],
)
@pytest.mark.asyncio
async def test_fred_query_param_auth_and_live_fixture_mapping(
    series_id,
    fixture,
    expected_latest,
):
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads(load_fixture(fixture))
    provider = FredProvider(config=CreConfig(fred_api_key="fred-key"), fetch=fetch)
    series = await provider.series(series_id)
    assert "series%2Fobservations" not in fetch.get_json.await_args.args[0]
    assert f"series_id={series_id}" in fetch.get_json.await_args.args[0]
    assert "api_key=fred-key" in fetch.get_json.await_args.args[0]
    assert "headers" not in fetch.get_json.await_args.kwargs
    assert series.points[-1] == expected_latest


@pytest.mark.asyncio
async def test_fred_missing_key_disables_provider_without_network():
    fetch = AsyncMock()
    provider = FredProvider(config=CreConfig(fred_api_key=None), fetch=fetch)
    with pytest.raises(ProviderUnavailableError):
        await provider.series("DGS10")
    fetch.get_json.assert_not_awaited()
