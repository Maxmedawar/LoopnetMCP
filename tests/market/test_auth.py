"""AuthSpec and GovApiClient injection tests."""

from unittest.mock import AsyncMock

import pytest

from cre_mcp.market.base import AuthSpec, GovApiClient


@pytest.mark.asyncio
async def test_none_auth_leaves_request_untouched():
    fetch = AsyncMock()
    client = GovApiClient(fetch, AuthSpec(kind="none"), "https://example.gov/api")
    await client.get("data", {"year": 2025})
    fetch.get_json.assert_awaited_once_with("https://example.gov/api/data?year=2025")


@pytest.mark.asyncio
async def test_query_param_auth_merges_secret():
    fetch = AsyncMock()
    client = GovApiClient(
        fetch,
        AuthSpec(kind="query_param", param_name="key", secret="abc"),
        "https://example.gov/api",
    )
    await client.get("data", {"year": 2025})
    fetch.get_json.assert_awaited_once_with(
        "https://example.gov/api/data?year=2025&key=abc"
    )


@pytest.mark.asyncio
async def test_bearer_auth_sets_header():
    fetch = AsyncMock()
    client = GovApiClient(
        fetch,
        AuthSpec(kind="bearer", secret="abc"),
        "https://example.gov/api",
    )
    await client.get("data")
    fetch.get_json.assert_awaited_once_with(
        "https://example.gov/api/data",
        headers={"Authorization": "Bearer abc"},
    )


@pytest.mark.asyncio
async def test_body_field_auth_merges_secret_without_mutating_body():
    fetch = AsyncMock()
    body = {"seriesid": ["A"]}
    client = GovApiClient(
        fetch,
        AuthSpec(kind="body_field", param_name="registrationkey", secret="abc"),
        "https://example.gov/api",
    )
    await client.post("data", body)
    assert body == {"seriesid": ["A"]}
    fetch.post_json.assert_awaited_once_with(
        "https://example.gov/api/data",
        {"seriesid": ["A"], "registrationkey": "abc"},
    )

