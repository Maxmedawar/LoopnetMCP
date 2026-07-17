"""HUD USPS crosswalk tests."""

import json
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.geo.crosswalk import GeoCrosswalk
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_static_crosswalk_works_without_hud_token(tmp_path):
    fetch = AsyncMock()
    crosswalk = GeoCrosswalk(
        CreConfig(cache_db_path=tmp_path / "geo.db", hud_api_token=None),
        fetch=fetch,
        hud_token=None,
    )

    assert await crosswalk.zip_to_county("78701") == "48453"
    assert await crosswalk.zip_to_cbsa("78701") == "12420"
    fetch.get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_hud_rows_persist_and_dominant_ratio_wins(tmp_path):
    fetch = AsyncMock()
    fetch.get_json.side_effect = [
        json.loads(load_fixture("hud/usps_zip_county.json")),
        json.loads(load_fixture("hud/usps_zip_cbsa.json")),
    ]
    crosswalk = GeoCrosswalk(
        CreConfig(cache_db_path=tmp_path / "geo.db"),
        fetch=fetch,
        hud_token="hud-token",
    )

    assert await crosswalk.zip_to_county("78701") == "48453"
    url = fetch.get_json.await_args.args[0]
    assert "usps?" in url and "type=2" in url and "query=78701" in url
    assert fetch.get_json.await_args.kwargs["headers"] == {
        "Authorization": "Bearer hud-token"
    }

    assert await crosswalk.zip_to_cbsa("78701") == "12420"
    assert "type=3" in fetch.get_json.await_args.args[0]

    fetch.get_json.reset_mock()
    assert await crosswalk.zip_to_county("78701") == "48453"
    fetch.get_json.assert_not_awaited()
