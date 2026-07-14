"""Browser fetcher for bypassing JavaScript challenges using nodriver."""

import asyncio
import json
import logging
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.http.errors import FetchClientError

logger = logging.getLogger(__name__)

# Akamai challenge markers
_CHALLENGE_MARKERS = ("sec-if-cpt-container", "behavioral-content", "/akam/13/pixel_")
_CHALLENGE_MAX_LENGTH = 10_000
_CLOUDFLARE_MARKERS = (
    "just a moment",
    "cf-challenge",
    "__cf_chl",
    "cf-mitigated",
    "cloudflare ray id",
)
_IMPERVA_MARKERS = (
    "_incapsula_resource",
    "incapsula incident id",
    "imperva",
)


class BrowserFetchError(FetchClientError):
    """Raised when the browser-based fetch fails."""


def is_challenge_page(html: str) -> bool:
    """Detect an Akamai JS challenge page.

    Returns True if the HTML contains known challenge markers AND is
    shorter than the threshold (real pages are much larger).
    """
    if len(html) > _CHALLENGE_MAX_LENGTH:
        return False
    return any(marker in html for marker in _CHALLENGE_MARKERS)


def is_cloudflare_challenge(text: str) -> bool:
    """Return whether a response is a Cloudflare 403/503 interstitial."""
    lowered = text.lower()
    return any(marker in lowered for marker in _CLOUDFLARE_MARKERS)


def is_imperva_challenge(text: str) -> bool:
    """Return whether a response is an Imperva/Incapsula interstitial."""
    lowered = text.lower()
    return any(marker in lowered for marker in _IMPERVA_MARKERS)


class BrowserFetcher:
    """Lazy-initialized nodriver browser for solving JS challenges."""

    def __init__(self, config: CreConfig | None = None):
        self._config = config or CreConfig()
        self._browser = None
        self._lock = asyncio.Lock()

    def _launch_options(self) -> dict[str, Any]:
        """Build nodriver launch options without exposing configured secrets."""
        options: dict[str, Any] = {
            "headless": self._config.browser_headless,
        }
        if self._config.browser_path is not None:
            options["browser_executable_path"] = str(self._config.browser_path)
        # Chromium refuses to start its sandbox when the process can reach root
        # privileges (the classic "Running as root without --no-sandbox is not
        # supported" crash seen under launchd/containers). These flags make the
        # headless browser start reliably as a service.
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
        if self._config.proxy_url is not None:
            browser_args.append(
                "--proxy-server=" + self._config.proxy_url.get_secret_value()
            )
        options["browser_args"] = browser_args
        return options

    async def _ensure_browser(self):
        """Launch the nodriver browser if not already running."""
        if self._browser is not None:
            return

        async with self._lock:
            if self._browser is not None:
                return

            try:
                import nodriver
            except ImportError as exc:
                raise BrowserFetchError(
                    "nodriver is not installed. Run: pip install nodriver"
                ) from exc

            self._browser = await nodriver.start(**self._launch_options())

    async def fetch(self, url: str) -> str:
        """Fetch a URL using the browser, waiting for the challenge to resolve."""
        await self._ensure_browser()

        page = await self._browser.get(url)
        try:
            # Wait for real page content to appear (challenge resolves via JS)
            deadline = asyncio.get_event_loop().time() + self._config.browser_challenge_wait_seconds
            html = ""
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1)
                html = await page.get_content()
                if not is_challenge_page(html) and len(html) > 1000:
                    break

            if not html:
                html = await page.get_content()

            if is_challenge_page(html):
                raise BrowserFetchError(
                    f"Challenge page persisted after browser fetch for URL: {url}"
                )

            return html
        finally:
            await page.close()

    async def fetch_api(
        self,
        url: str,
        *,
        method: str = "GET",
        body: Any = None,
        warmup_url: str = "https://www.crexi.com/",
    ) -> str:
        """Fetch API text from an in-page context with browser cookies."""
        await self._ensure_browser()

        page = await self._browser.get(warmup_url)
        try:
            await asyncio.sleep(1)
            method = method.upper()
            request_options: dict[str, Any] = {
                "method": method,
                "credentials": "include",
                "headers": {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            }
            if method != "GET" and body is not None:
                request_options["body"] = json.dumps(body)

            expression = """
                (async () => {
                    const response = await fetch(%s, %s);
                    const text = await response.text();
                    return JSON.stringify({status: response.status, text});
                })()
            """ % (json.dumps(url), json.dumps(request_options))
            raw_result = await page.evaluate(
                expression,
                await_promise=True,
                return_by_value=True,
            )
            result = json.loads(raw_result)
            status = int(result.get("status", 0))
            text = str(result.get("text", ""))
            if status < 200 or status >= 300:
                raise BrowserFetchError(
                    f"Browser API fetch returned status {status} for URL: {url}"
                )
            return text
        except BrowserFetchError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BrowserFetchError(
                f"Browser API fetch returned an invalid result for URL: {url}"
            ) from exc
        finally:
            await page.close()

    async def close(self):
        """Shut down the browser."""
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception:
                pass
            self._browser = None


CHALLENGE_DETECTORS = {
    "akamai": is_challenge_page,
    "cloudflare": is_cloudflare_challenge,
    "imperva": is_imperva_challenge,
}
