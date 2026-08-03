"""Browser fetcher for bypassing JavaScript challenges using nodriver."""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr

from cre_mcp.config import CreConfig
from cre_mcp.http.errors import FetchClientError
from cre_mcp.source_rights.gate import (
    SourceRightsDeniedError,
    is_hosted_execution,
    require_url,
)
from cre_mcp.source_rights.output import redact_url
from cre_mcp.source_rights.registry import (
    SourceRightsRegistryError,
    get_rights_registry,
)

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


def _is_access_denied(html: str) -> bool:
    """Detect a hard Akamai/edge 'Access Denied' block (a tiny 403 page)."""
    if len(html) > 5000:
        return False
    lowered = html.lower()
    return "access denied" in lowered and "don't have permission" in lowered


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
        self._warmed: set[str] = set()
        self._guarded_tabs: set[int] = set()
        self._secret_values = tuple(
            value.get_secret_value()
            for field_name in type(self._config).model_fields
            if isinstance((value := getattr(self._config, field_name, None)), SecretStr)
            and value.get_secret_value()
        )

    def _safe_url(self, url: str) -> str:
        query_credentials: tuple[str, ...] = ()
        try:
            registry = get_rights_registry(
                self._config.source_rights_registry_path
            )
            record = registry.for_url(url)
            if record is not None:
                query_credentials = tuple(record.query_credentials)
        except (SourceRightsRegistryError, TypeError, ValueError):
            pass
        return redact_url(
            url,
            query_credentials,
            secret_values=self._secret_values,
        )

    def _require_authorized_url(self, url: str, *, method: str = "GET") -> None:
        if is_hosted_execution(self._config):
            raise BrowserFetchError(
                "source-rights denied: hosted browser navigation cannot prove "
                "redirected egress"
            )
        try:
            require_url(url, method=method, config=self._config)
        except SourceRightsDeniedError as exc:
            raise BrowserFetchError(str(exc)) from None

    def _launch_options(self) -> dict[str, Any]:
        """Build nodriver launch options without exposing configured secrets."""
        options: dict[str, Any] = {
            "headless": self._config.browser_headless,
            # nodriver's own sandbox flag — this is what actually adds --no-sandbox
            # and lets Chromium start under a service/launchd (root-like) context.
            # The classic "Failed to connect to browser ... running as root" crash
            # is nodriver refusing to start with the sandbox enabled.
            "sandbox": False,
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

    async def _install_request_guard(self) -> None:
        """Pause every browser request and authorize it before Chromium sends it."""
        try:
            from nodriver import cdp
        except ImportError as exc:
            raise BrowserFetchError(
                "nodriver is not installed. Run: pip install nodriver"
            ) from exc

        tabs = getattr(self._browser, "tabs", None)
        if not isinstance(tabs, (list, tuple)) or not tabs:
            raise BrowserFetchError(
                "source-rights denied: browser request interception is unavailable"
            )
        tab = tabs[0]
        tab_key = id(tab)
        if tab_key in self._guarded_tabs:
            return

        async def authorize_request(event, connection) -> None:
            request = getattr(event, "request", None)
            request_url = getattr(request, "url", "")
            request_method = getattr(request, "method", "GET")
            try:
                self._require_authorized_url(
                    request_url,
                    method=request_method,
                )
            except BrowserFetchError:
                await connection.send(
                    cdp.fetch.fail_request(
                        event.request_id,
                        cdp.network.ErrorReason.BLOCKED_BY_CLIENT,
                    )
                )
                return
            await connection.send(cdp.fetch.continue_request(event.request_id))

        tab.add_handler(cdp.fetch.RequestPaused, authorize_request)
        await tab.send(
            cdp.fetch.enable(
                patterns=[
                    cdp.fetch.RequestPattern(
                        url_pattern="*",
                        request_stage=cdp.fetch.RequestStage.REQUEST,
                    )
                ]
            )
        )
        self._guarded_tabs.add(tab_key)

    async def _navigate(self, url: str):
        """Navigate only after request interception is active on the browser tab."""
        self._require_authorized_url(url)
        await self._install_request_guard()
        return await self._browser.get(url)

    async def _warmup(self, url: str) -> None:
        """Visit a host's homepage once per session to earn edge/bot cookies.

        Akamai (LoopNet) hard-blocks deep pages with a 342-byte "Access Denied"
        unless the session first establishes _abck / bm_sz cookies from the
        homepage. We do this once per host per browser session, then reuse the
        cookied session for every subsequent fetch.
        """
        self._require_authorized_url(url)
        parsed = urlparse(self._safe_url(url))
        host = parsed.netloc
        if not host or host in self._warmed:
            return
        home = f"{parsed.scheme or 'https'}://{host}/"
        self._require_authorized_url(home)
        self._warmed.add(host)
        try:
            # Navigate the main tab to the homepage and let the edge cookies
            # settle. Do NOT close the tab — the subsequent fetch reuses this
            # same cookied session/tab.
            await self._navigate(home)
            await asyncio.sleep(self._config.browser_challenge_wait_seconds)
        except Exception as exc:
            logger.warning(
                "browser warmup failed for %s (%s)",
                host,
                type(exc).__name__,
            )

    async def fetch(self, url: str) -> str:
        """Fetch a URL using the browser, waiting for the challenge to resolve."""
        self._require_authorized_url(url)
        await self._ensure_browser()
        await self._warmup(url)

        page = await self._navigate(url)
        try:
            # Wait for real page content to appear (challenge resolves via JS)
            deadline = asyncio.get_event_loop().time() + self._config.browser_challenge_wait_seconds
            html = ""
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1)
                html = await page.get_content()
                if not is_challenge_page(html) and not _is_access_denied(html) and len(html) > 1000:
                    break

            if not html:
                html = await page.get_content()

            if is_challenge_page(html):
                raise BrowserFetchError(
                    "Challenge page persisted after browser fetch for URL: "
                    f"{self._safe_url(url)}"
                )
            if _is_access_denied(html):
                raise BrowserFetchError(
                    "Edge bot-block (Access Denied) persisted for URL: "
                    f"{self._safe_url(url)}"
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
        self._require_authorized_url(url, method=method)
        self._require_authorized_url(warmup_url)
        await self._ensure_browser()

        page = await self._navigate(warmup_url)
        try:
            await asyncio.sleep(1)
            method = method.upper()
            request_options: dict[str, Any] = {
                "method": method,
                "credentials": "include",
                "redirect": "manual",
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
                    return JSON.stringify({
                        status: response.status,
                        text,
                        redirected: response.redirected,
                        url: response.url
                    });
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
            if bool(result.get("redirected")) or status < 200 or status >= 300:
                raise BrowserFetchError(
                    f"Browser API fetch returned status {status} for URL: "
                    f"{self._safe_url(url)}"
                )
            return text
        except BrowserFetchError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError):
            raise BrowserFetchError(
                "Browser API fetch returned an invalid result for URL: "
                f"{self._safe_url(url)}"
            ) from None
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
            self._guarded_tabs.clear()


CHALLENGE_DETECTORS = {
    "akamai": is_challenge_page,
    "cloudflare": is_cloudflare_challenge,
    "imperva": is_imperva_challenge,
}
