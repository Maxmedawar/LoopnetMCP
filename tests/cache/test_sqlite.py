"""Persistent SQLite cache and FetchClient write-through tests."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.cache import SQLiteCache, TTLCache
from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient
from cre_mcp.market.census import CensusProvider
from cre_mcp.models import GeoLevel, GeoRef
from tests.conftest import MockResponse, load_fixture


@pytest.mark.asyncio
async def test_sqlite_set_get_expiry_and_eviction(tmp_path):
    cache = SQLiteCache(tmp_path / "nested" / "cache.db", ttl_seconds=60)
    with patch("cre_mcp.cache.sqlite.time.time", return_value=100.0):
        await cache.set("fresh", {"value": 1})
        await cache.set("expired", "old", ttl_seconds=1)
    with patch("cre_mcp.cache.sqlite.time.time", return_value=102.0):
        assert await cache.get("fresh") == {"value": 1}
        assert await cache.get("expired") is None
        assert await cache.evict_expired() == 0  # get already evicted the row

    await cache.clear()
    assert await cache.get("fresh") is None


@pytest.mark.asyncio
async def test_persistent_policy_second_client_skips_network(tmp_path):
    config = CreConfig(
        cache_db_path=tmp_path / "cache.db",
        request_delay_seconds=0,
        max_retries=1,
    )
    persistent = SQLiteCache(config.cache_db_path)
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )

    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.get = AsyncMock(
            return_value=MockResponse(200, load_fixture("census/acs5_profile.json"))
        )
        session.close = AsyncMock()
        async with FetchClient(
            config=config,
            cache=TTLCache(),
            persistent_cache=persistent,
        ) as first:
            metrics = await CensusProvider(config=config, fetch=first).acs5_profile(
                geo, 2024
            )
            assert metrics["population"].value == 1_330_015
        session.get.assert_awaited_once()

    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        async with FetchClient(
            config=config,
            cache=TTLCache(),
            persistent_cache=SQLiteCache(config.cache_db_path),
        ) as second:
            metrics = await CensusProvider(config=config, fetch=second).acs5_profile(
                geo, 2024
            )
            assert metrics["population"].value == 1_330_015
        session_class.assert_not_called()
