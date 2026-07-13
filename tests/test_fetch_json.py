"""Tests for JSON requests through the shared FetchClient policy path."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.cache import TTLCache
from cre_mcp.config import CreConfig
from cre_mcp.http.fetch import FetchClient
from tests.conftest import MockResponse

CREXI_URL = "https://api.crexi.com/assets/search"
CREXI_DETAIL_URL = "https://api.crexi.com/assets/2622985"
AUCTIONCOM_URL = "https://graph.auction.com/graphql"


def _client(cache=None) -> FetchClient:
    client = FetchClient(
        config=CreConfig(request_delay_seconds=0, max_retries=1),
        cache=cache,
    )
    client._warmed_up_hosts.add("api.crexi.com")
    return client


@pytest.mark.asyncio
async def test_post_json_decodes_and_caches_by_stable_body_hash():
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.post = AsyncMock(
            side_effect=[
                MockResponse(200, '{"data":[{"id":1}]}'),
                MockResponse(200, '{"data":[{"id":2}]}'),
            ]
        )
        session.close = AsyncMock()
        async with _client(cache=TTLCache()) as client:
            first = await client.post_json(CREXI_URL, {"count": 1, "offset": 0})
            cached = await client.post_json(CREXI_URL, {"offset": 0, "count": 1})
            second = await client.post_json(CREXI_URL, {"count": 1, "offset": 1})

    assert first == cached == {"data": [{"id": 1}]}
    assert second == {"data": [{"id": 2}]}
    assert session.post.await_count == 2


@pytest.mark.asyncio
async def test_get_json_decodes_detail_response():
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.get = AsyncMock(return_value=MockResponse(200, '{"id":2622985}'))
        session.close = AsyncMock()
        async with _client() as client:
            result = await client.get_json(CREXI_DETAIL_URL)

    assert result == {"id": 2622985}
    session.get.assert_awaited_once_with(CREXI_DETAIL_URL)


def test_crexi_policy_has_cloudflare_headers_and_cache_windows():
    client = _client()
    policy = client._policy_for_url(CREXI_URL)

    assert policy.impersonate == "chrome136"
    assert policy.default_headers == {
        "Origin": "https://www.crexi.com",
        "Referer": "https://www.crexi.com/",
    }
    assert policy.browser_fallback is True
    assert policy.cache_namespace == "crexi"
    assert policy.cache_ttl_seconds == 15 * 60
    assert policy.detail_cache_ttl_seconds == 2 * 60 * 60


def test_auctioncom_policy_has_antibot_fallback_and_persistent_cache():
    client = _client()
    policy = client._policy_for_url(AUCTIONCOM_URL)

    assert policy.impersonate == "chrome136"
    assert policy.warmup_url == "https://www.auction.com/"
    assert policy.browser_fallback is True
    assert policy.cache_namespace == "auction-com"
    assert policy.persist is True


@pytest.mark.asyncio
async def test_cloudflare_json_response_uses_in_page_browser_fallback():
    challenge = "<html><title>Just a moment...</title><script>__cf_chl</script></html>"
    body = {"includeUnpriced": True, "count": 1}
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.post = AsyncMock(return_value=MockResponse(403, challenge))
        session.close = AsyncMock()
        with patch(
            "cre_mcp.http.browser.BrowserFetcher.fetch_api",
            new_callable=AsyncMock,
            return_value='{"data":[]}',
        ) as browser_fetch:
            async with _client() as client:
                result = await client.post_json(CREXI_URL, body)

    assert result == {"data": []}
    browser_fetch.assert_awaited_once_with(
        CREXI_URL,
        method="POST",
        body=body,
        warmup_url="https://www.crexi.com/",
    )
