"""Tests for the nodriver browser fetcher."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nodriver import cdp

from cre_mcp.config import LoopnetConfig
from cre_mcp.scraper.browser import (
    BrowserFetchError,
    BrowserFetcher,
    is_challenge_page,
    is_cloudflare_challenge,
    is_imperva_challenge,
)


def _browser_config(**overrides):
    return LoopnetConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={
            "listing.crexi": True,
            "listing.loopnet": True,
        },
        **overrides,
    )


def _mock_browser(page):
    page.add_handler = MagicMock()
    page.send = AsyncMock()
    browser = MagicMock()
    browser.tabs = [page]
    browser.get = AsyncMock(return_value=page)
    return browser


# --- is_challenge_page tests ---


def test_is_challenge_page_detects_sec_if_cpt():
    html = '<html><div id="sec-if-cpt-container">challenge</div></html>'
    assert is_challenge_page(html) is True


def test_is_challenge_page_detects_behavioral_content():
    html = "<html><div>behavioral-content marker</div></html>"
    assert is_challenge_page(html) is True


def test_is_challenge_page_detects_akam_pixel():
    html = "<html><script src='/akam/13/pixel_abc'></script></html>"
    assert is_challenge_page(html) is True


def test_is_challenge_page_rejects_real_content():
    html = "<html><body><h1>Real Property Listing</h1>" + "x" * 15_000 + "</body></html>"
    assert is_challenge_page(html) is False


def test_is_challenge_page_rejects_large_page_with_markers():
    """A large page that happens to contain a marker string is NOT a challenge."""
    html = '<html><div id="sec-if-cpt-container">' + "x" * 15_000 + "</div></html>"
    assert is_challenge_page(html) is False


def test_is_challenge_page_rejects_normal_small_page():
    html = "<html><body><h1>Hello</h1></body></html>"
    assert is_challenge_page(html) is False


@pytest.mark.parametrize(
    "html",
    [
        "<title>Just a moment...</title>",
        "<script>window.__cf_chl_opt = {}</script>",
        "<div class='cf-challenge'>Checking your browser</div>",
        "<meta name='cf-mitigated' content='challenge'>",
    ],
)
def test_is_cloudflare_challenge_detects_interstitial(html):
    assert is_cloudflare_challenge(html) is True


def test_is_cloudflare_challenge_rejects_json():
    assert is_cloudflare_challenge('{"data": [], "totalCount": 0}') is False


def test_is_imperva_challenge_detects_auctioncom_interstitial():
    html = '<meta name="robots" content="noindex"><script src="/_Incapsula_Resource"></script>'
    assert is_imperva_challenge(html) is True
    assert is_imperva_challenge('{"data":{"listings":[]}}') is False


# --- BrowserFetcher tests ---


@pytest.mark.asyncio
async def test_browser_fetcher_returns_html():
    """BrowserFetcher.fetch returns page HTML when challenge resolves."""
    expected_html = "<html><body><article class='placard'>Listing</article>" + "x" * 2000 + "</body></html>"

    mock_page = AsyncMock()
    mock_page.get_content = AsyncMock(return_value=expected_html)
    mock_page.close = AsyncMock()

    fetcher = BrowserFetcher(config=_browser_config())
    mock_browser = _mock_browser(mock_page)
    fetcher._browser = mock_browser

    result = await fetcher.fetch("https://www.loopnet.com/listing/123")
    assert result == expected_html
    # First a homepage warmup (earn edge cookies), then the target fetch.
    mock_browser.get.assert_any_call("https://www.loopnet.com/")
    mock_browser.get.assert_any_call("https://www.loopnet.com/listing/123")
    assert mock_browser.get.call_count == 2
    mock_page.close.assert_called_once()


@pytest.mark.asyncio
async def test_browser_fetcher_raises_on_persistent_challenge():
    """BrowserFetcher.fetch raises if challenge page persists after browser fetch."""
    challenge_html = '<html><div id="sec-if-cpt-container">blocked</div></html>'

    mock_page = AsyncMock()
    mock_page.get_content = AsyncMock(return_value=challenge_html)
    mock_page.close = AsyncMock()

    fetcher = BrowserFetcher(
        config=_browser_config(browser_challenge_wait_seconds=2.0)
    )
    mock_browser = _mock_browser(mock_page)
    fetcher._browser = mock_browser

    with pytest.raises(BrowserFetchError, match="Challenge page persisted"):
        await fetcher.fetch("https://www.loopnet.com/listing/123")
    mock_page.close.assert_called_once()


@pytest.mark.asyncio
async def test_browser_fetcher_close_cleans_up():
    """BrowserFetcher.close shuts down the browser."""
    fetcher = BrowserFetcher(config=_browser_config())
    mock_browser = MagicMock()
    fetcher._browser = mock_browser

    await fetcher.close()
    mock_browser.stop.assert_called_once()
    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_browser_fetcher_close_noop_when_not_started():
    """BrowserFetcher.close is a no-op when browser was never launched."""
    fetcher = BrowserFetcher(config=_browser_config())
    await fetcher.close()  # Should not raise
    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_browser_fetcher_fetch_api_runs_in_page_and_returns_text():
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(
        return_value='{"status": 200, "text": "{\\"data\\":[]}"}'
    )
    mock_page.close = AsyncMock()

    fetcher = BrowserFetcher(config=_browser_config())
    mock_browser = _mock_browser(mock_page)
    fetcher._browser = mock_browser

    result = await fetcher.fetch_api(
        "https://api.crexi.com/assets/search",
        method="POST",
        body={"count": 1},
    )

    assert result == '{"data":[]}'
    mock_browser.get.assert_awaited_once_with("https://www.crexi.com/")
    expression = mock_page.evaluate.await_args.args[0]
    assert "fetch(" in expression
    assert "api.crexi.com/assets/search" in expression
    assert '\\"count\\": 1' in expression
    assert '"redirect": "manual"' in expression
    mock_page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_request_guard_blocks_redirect_to_unapproved_source():
    page = AsyncMock()
    page.add_handler = MagicMock()
    page.send = AsyncMock()
    browser = MagicMock()
    browser.tabs = [page]
    fetcher = BrowserFetcher(config=_browser_config())
    fetcher._browser = browser

    await fetcher._install_request_guard()
    callback = page.add_handler.call_args.args[1]
    event = SimpleNamespace(
        request_id="redirect-request",
        request=SimpleNamespace(
            url="https://redirect-escape.example.test/private",
            method="GET",
        ),
    )
    fail_command = object()
    with patch.object(
        cdp.fetch,
        "fail_request",
        return_value=fail_command,
    ) as fail_request, patch.object(
        cdp.fetch,
        "continue_request",
        return_value=object(),
    ) as continue_request:
        await callback(event, page)

    fail_request.assert_called_once_with(
        "redirect-request",
        cdp.network.ErrorReason.BLOCKED_BY_CLIENT,
    )
    continue_request.assert_not_called()
    page.send.assert_awaited_with(fail_command)
