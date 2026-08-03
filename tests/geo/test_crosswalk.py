"""HUD USPS crosswalk tests."""

import json
import logging
import time
from unittest.mock import AsyncMock

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.geo.crosswalk import GeoCrosswalk
from tests.conftest import load_fixture, write_cached_rights_registry


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
    rights_path = write_cached_rights_registry(
        tmp_path,
        {"geo.hud_usps_crosswalk"},
    )
    crosswalk = GeoCrosswalk(
        CreConfig(
            _env_file=None,
            transport="stdio",
            cache_db_path=tmp_path / "geo.db",
            source_rights_registry_path=rights_path,
            source_rights_enabled={"geo.hud_usps_crosswalk": True},
        ),
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


@pytest.mark.asyncio
async def test_expired_hud_row_is_deleted_and_never_returned(tmp_path):
    fetch = AsyncMock()
    fetch.get_json.return_value = {"data": {"results": []}}
    rights_path = write_cached_rights_registry(
        tmp_path,
        {"geo.hud_usps_crosswalk"},
    )
    crosswalk = GeoCrosswalk(
        CreConfig(
            _env_file=None,
            transport="stdio",
            cache_db_path=tmp_path / "geo.db",
            source_rights_registry_path=rights_path,
            source_rights_enabled={"geo.hud_usps_crosswalk": True},
        ),
        fetch=fetch,
        hud_token="hud-token",
    )
    crosswalk._store("xwalk_zip_county", "county_fips", "99999", [("12345", 1.0)])
    with crosswalk._connect() as connection:
        connection.execute(
            "UPDATE xwalk_zip_county SET updated_at = ? WHERE zip = ?",
            (time.time() - 10_000, "99999"),
        )

    assert await crosswalk.zip_to_county("99999") is None
    assert crosswalk._lookup("xwalk_zip_county", "county_fips", "99999") is None


@pytest.mark.asyncio
async def test_malformed_hud_row_never_logs_source_native_payload(tmp_path, caplog):
    secret = "TOPSECRET-hud-upstream"
    fetch = AsyncMock()
    fetch.get_json.return_value = {
        "data": {
            "results": [
                {
                    "geoid": "48453",
                    "res_ratio": "bad",
                    "diagnostic": f"api_key={secret}",
                }
            ]
        }
    }
    rights_path = write_cached_rights_registry(
        tmp_path,
        {"geo.hud_usps_crosswalk"},
    )
    crosswalk = GeoCrosswalk(
        CreConfig(
            _env_file=None,
            transport="stdio",
            cache_db_path=tmp_path / "geo.db",
            source_rights_registry_path=rights_path,
            source_rights_enabled={"geo.hud_usps_crosswalk": True},
        ),
        fetch=fetch,
        hud_token="hud-token",
    )

    with caplog.at_level(logging.WARNING):
        assert await crosswalk.zip_to_county("99999") is None

    assert "Ignoring malformed HUD crosswalk row" in caplog.text
    assert secret not in caplog.text
    assert "diagnostic" not in caplog.text
