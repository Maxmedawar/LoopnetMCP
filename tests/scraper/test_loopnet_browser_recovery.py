"""Failure-path tests for the LoopNet-specific browser hardening."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import cre_mcp.scraper.browser as browser_module
from cre_mcp.config import LoopnetConfig
from cre_mcp.http.errors import FetchBlockedError
from cre_mcp.scraper.browser import (
    BrowserFetchError,
    BrowserFetcher,
    loopnet_block_reason,
)
from cre_mcp.scraper.client import LoopnetClient


TEST_URL = "https://www.loopnet.com/search/retail/austin-tx/for-sale/"


@pytest.mark.parametrize(
    ("html", "reason"),
    [
        (
            "<html><h1>Access Denied</h1><p>You don't have permission "
            "to access this resource.</p></html>",
            "access_denied",
        ),
        (
            '<html><div id="sec-if-cpt-container">Please wait</div></html>',
            "akamai_challenge",
        ),
        (
            "<html><title>Verify you are human</title></html>",
            "akamai_challenge",
        ),
        (
            "<html><body>ordinary small page</body></html>",
            None,
        ),
    ],
)
def test_loopnet_block_reason_labels_interstitials(html, reason):
    assert loopnet_block_reason(html) == reason


@pytest.mark.asyncio
async def test_navigation_timeout_resets_once_before_retry():
    fetcher = BrowserFetcher()
    timeout = browser_module._BrowserOperationTimeout(
        "loopnet_blocked: browser_navigation_timeout"
    )
    expected = "<html>" + "x" * 2_000 + "</html>"
    fetcher._fetch_once = AsyncMock(side_effect=[timeout, expected])
    fetcher._reset_after_timeout = AsyncMock()

    result = await fetcher.fetch(TEST_URL)

    assert result == expected
    assert fetcher._fetch_once.await_count == 2
    fetcher._reset_after_timeout.assert_awaited_once_with(timeout)


@pytest.mark.asyncio
async def test_second_navigation_timeout_fast_fails_with_labeled_reason():
    fetcher = BrowserFetcher()
    first = browser_module._BrowserOperationTimeout(
        "loopnet_blocked: browser_navigation_timeout after 10s"
    )
    second = browser_module._BrowserOperationTimeout(
        "loopnet_blocked: browser_navigation_timeout after first retry"
    )
    third = browser_module._BrowserOperationTimeout(
        "loopnet_blocked: browser_navigation_timeout after final retry"
    )
    fetcher._fetch_once = AsyncMock(side_effect=[first, second, third])
    fetcher._reset_after_timeout = AsyncMock()

    with pytest.raises(
        BrowserFetchError,
        match="loopnet_blocked: browser_navigation_timeout after final retry",
    ):
        await fetcher.fetch(TEST_URL)

    assert fetcher._fetch_once.await_count == 3
    assert fetcher._reset_after_timeout.await_args_list == [
        ((first,), {}),
        ((second,), {}),
    ]


@pytest.mark.asyncio
async def test_persistent_access_denied_page_fast_fails_and_closes_tab():
    blocked_html = (
        "<html><h1>Access Denied</h1>"
        "<p>You don't have permission to access this resource.</p></html>"
    )
    page = AsyncMock()
    page.get_content.return_value = blocked_html
    page.close = AsyncMock()
    browser = MagicMock()
    browser.get = AsyncMock(return_value=page)

    fetcher = BrowserFetcher(
        config=LoopnetConfig(browser_challenge_wait_seconds=0.0)
    )
    fetcher._browser = browser
    fetcher._warmed.add("www.loopnet.com")

    with pytest.raises(
        BrowserFetchError,
        match="loopnet_blocked: access_denied persisted",
    ):
        await fetcher.fetch(TEST_URL)

    page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_discards_blocked_browser_session():
    client = LoopnetClient(config=LoopnetConfig(request_delay_seconds=0.0))
    browser = AsyncMock()
    browser.fetch.side_effect = BrowserFetchError(
        "loopnet_blocked: incomplete_page (39 bytes)"
    )
    client._browser_fetcher = browser
    policy = client._policy_for_url(TEST_URL)

    with pytest.raises(
        FetchBlockedError,
        match=r"loopnet_blocked: incomplete_page \(39 bytes\)",
    ):
        await client._fetch_with_browser(TEST_URL, policy, TEST_URL)

    browser.close.assert_awaited_once()
    assert client._browser_fetcher is None
