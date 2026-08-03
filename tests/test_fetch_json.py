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
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _client(cache=None, persistent_cache=None) -> FetchClient:
    client = FetchClient(
        config=CreConfig(
            request_delay_seconds=0,
            max_retries=1,
            source_rights_enabled={
                "listing.crexi": True,
                "listing.auction_com": True,
                "osm.overpass": True,
            },
        ),
        cache=cache,
        persistent_cache=persistent_cache,
    )
    client._warmed_up_hosts.add("api.crexi.com")
    client._enforce_rate_limit = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_post_json_decodes_without_cache_when_registry_ttl_is_zero():
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.post = AsyncMock(
            side_effect=[
                MockResponse(200, '{"data":[{"id":1}]}'),
                MockResponse(200, '{"data":[{"id":2}]}'),
                MockResponse(200, '{"data":[{"id":3}]}'),
            ]
        )
        session.close = AsyncMock()
        async with _client(cache=TTLCache()) as client:
            first = await client.post_json(CREXI_URL, {"count": 1, "offset": 0})
            repeated = await client.post_json(CREXI_URL, {"offset": 0, "count": 1})
            second = await client.post_json(CREXI_URL, {"count": 1, "offset": 1})

    assert first == {"data": [{"id": 1}]}
    assert repeated == {"data": [{"id": 2}]}
    assert second == {"data": [{"id": 3}]}
    assert session.post.await_count == 3


@pytest.mark.asyncio
async def test_post_form_json_uses_form_body_headers_and_cache():
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "cre-mcp-test/1.0",
    }
    persistent = AsyncMock()
    persistent.get.return_value = None
    with patch("cre_mcp.http.fetch.AsyncSession") as session_class:
        session = session_class.return_value
        session.post = AsyncMock(return_value=MockResponse(200, '{"elements":[]}'))
        session.close = AsyncMock()
        async with _client(
            cache=TTLCache(), persistent_cache=persistent
        ) as client:
            first = await client.post_form_json(
                OVERPASS_URL,
                {"data": "[out:json];node(1);out;"},
                headers=headers,
            )
            cached = await client.post_form_json(
                OVERPASS_URL,
                {"data": "[out:json];node(1);out;"},
                headers=headers,
            )

    assert first == cached == {"elements": []}
    assert session.post.await_count == 2
    session.post.assert_awaited_with(
        OVERPASS_URL,
        data={"data": "[out:json];node(1);out;"},
        headers=headers,
    )
    persistent.get.assert_not_awaited()


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
    assert policy.cache_ttl_seconds == 0
    assert policy.detail_cache_ttl_seconds == 0


def test_auctioncom_policy_has_antibot_fallback_but_no_raw_cache():
    client = _client()
    policy = client._policy_for_url(AUCTIONCOM_URL)

    assert policy.impersonate == "chrome136"
    assert policy.warmup_url == "https://www.auction.com/"
    assert policy.browser_fallback is True
    assert policy.cache_namespace == "auction-com"
    assert policy.cache_ttl_seconds == 0
    assert policy.persistent_cache_ttl_seconds == 0
    assert policy.persist is False


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
