"""LoopNet-hardened browser fetcher and backward-compatible exports."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from cre_mcp.http.browser import (
    CHALLENGE_DETECTORS,
    BrowserFetchError,
    BrowserFetcher as _BaseBrowserFetcher,
    is_challenge_page,
    is_cloudflare_challenge,
    is_imperva_challenge,
)
logger = logging.getLogger(__name__)

_INCOMPLETE_PAGE_LENGTH = 1_000
_MAX_OPERATION_TIMEOUT_SECONDS = 10.0
_MAX_BROWSER_ATTEMPTS = 3
_ADDITIONAL_CHALLENGE_MARKERS = (
    "verify you are human",
    "akamai bot manager",
    "challenge-platform",
)


def loopnet_block_reason(html: str) -> str | None:
    """Return a stable reason for a known LoopNet edge/interstitial page."""
    lowered = html.lower()
    if len(html) <= 5_000 and (
        "access denied" in lowered and "don't have permission" in lowered
    ):
        return "access_denied"
    if is_challenge_page(html):
        return "akamai_challenge"
    if len(html) <= 50_000 and any(
        marker in lowered for marker in _ADDITIONAL_CHALLENGE_MARKERS
    ):
        return "akamai_challenge"
    return None


class _BrowserOperationTimeout(BrowserFetchError):
    """Internal signal that the browser process/session must be replaced."""


class BrowserFetcher(_BaseBrowserFetcher):
    """Browser fetcher with bounded navigation and one clean-session retry.

    A timed-out CDP navigation leaves nodriver's tab connection unusable: later
    content, cookie, and screenshot commands queue behind the same wedged command.
    Stop that browser before retrying so a long-running MCP process cannot retain
    a poisoned session indefinitely.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fetch_lock = asyncio.Lock()
        self._runtime_browser_path: Path | None = None
        self._fallback_attempted = False

    @property
    def _operation_timeout(self) -> float:
        configured = max(float(self._config.browser_timeout_seconds), 1.0)
        return min(configured, _MAX_OPERATION_TIMEOUT_SECONDS)

    def _launch_options(self):
        options = super()._launch_options()
        if self._runtime_browser_path is not None:
            options["browser_executable_path"] = str(self._runtime_browser_path)
        return options

    def _fallback_browser_path(self) -> Path | None:
        """Find a local Chrome only after the configured executable wedges."""
        if sys.platform != "darwin":
            return None
        candidates = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home()
            / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        )
        configured = self._runtime_browser_path or self._config.browser_path
        for candidate in candidates:
            if candidate.is_file() and (
                configured is None or candidate != Path(configured)
            ):
                return candidate
        return None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            await asyncio.wait_for(
                super()._ensure_browser(),
                timeout=self._operation_timeout,
            )
        except TimeoutError:
            raise _BrowserOperationTimeout(
                "loopnet_blocked: browser_start_timeout "
                f"after {self._operation_timeout:g}s"
            ) from None
        except BrowserFetchError:
            raise
        except Exception:
            raise _BrowserOperationTimeout(
                "loopnet_blocked: browser_start_failed"
            ) from None

    async def _navigate(self, url: str):
        self._require_authorized_url(url)
        try:
            await self._install_request_guard()
            return await asyncio.wait_for(
                self._browser.get(url),
                timeout=self._operation_timeout,
            )
        except TimeoutError:
            raise _BrowserOperationTimeout(
                "loopnet_blocked: browser_navigation_timeout "
                f"after {self._operation_timeout:g}s for URL: "
                f"{self._safe_url(url)}"
            ) from None
        except BrowserFetchError:
            raise
        except Exception:
            raise BrowserFetchError(
                "loopnet_blocked: browser_navigation_failed for URL: "
                f"{self._safe_url(url)}"
            ) from None

    async def _warmup(self, url: str) -> None:
        """Warm the host, marking it ready only after navigation succeeds."""
        self._require_authorized_url(url)
        parsed = urlparse(self._safe_url(url))
        host = parsed.netloc
        if not host or host in self._warmed:
            return
        home = f"{parsed.scheme or 'https'}://{host}/"
        await self._navigate(home)
        await asyncio.sleep(self._config.browser_challenge_wait_seconds)
        self._warmed.add(host)

    async def _content(self, page, url: str) -> str:
        try:
            return await asyncio.wait_for(
                page.get_content(),
                timeout=self._operation_timeout,
            )
        except TimeoutError:
            raise _BrowserOperationTimeout(
                "loopnet_blocked: browser_content_timeout "
                f"after {self._operation_timeout:g}s for URL: "
                f"{self._safe_url(url)}"
            ) from None
        except Exception:
            raise BrowserFetchError(
                "loopnet_blocked: browser_content_failed for URL: "
                f"{self._safe_url(url)}"
            ) from None

    async def _fetch_once(self, url: str) -> str:
        self._require_authorized_url(url)
        await self._ensure_browser()
        await self._warmup(url)

        page = await self._navigate(url)
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._config.browser_challenge_wait_seconds
            html = ""
            reason: str | None = None
            while loop.time() < deadline:
                await asyncio.sleep(0.5)
                html = await self._content(page, url)
                reason = loopnet_block_reason(html)
                if reason is None and len(html) > _INCOMPLETE_PAGE_LENGTH:
                    return html

            if not html:
                html = await self._content(page, url)
            reason = loopnet_block_reason(html)
            if reason is not None:
                label = (
                    "Challenge page persisted"
                    if reason == "akamai_challenge"
                    else f"{reason} persisted"
                )
                raise BrowserFetchError(
                    f"loopnet_blocked: {label} for URL: "
                    f"{self._safe_url(url)}"
                )
            raise BrowserFetchError(
                "loopnet_blocked: incomplete_page "
                f"({len(html)} bytes) after readiness wait for URL: "
                f"{self._safe_url(url)}"
            )
        finally:
            try:
                await asyncio.wait_for(
                    page.close(),
                    timeout=self._operation_timeout,
                )
            except Exception:
                logger.debug(
                    "Unable to close LoopNet tab for %s",
                    self._safe_url(url),
                )

    async def _reset_after_timeout(self, error: BrowserFetchError) -> None:
        await super().close()
        self._warmed.clear()
        if not self._fallback_attempted:
            self._fallback_attempted = True
            fallback = self._fallback_browser_path()
            if fallback is not None:
                self._runtime_browser_path = fallback
                logger.warning(
                    "%s; retrying LoopNet with fallback browser executable %s",
                    error,
                    fallback,
                )
                return
        logger.warning("%s; retrying LoopNet with a fresh browser session", error)

    async def fetch(self, url: str) -> str:
        """Fetch with bounded replacement of a wedged or unbound browser."""
        self._require_authorized_url(url)
        async with self._fetch_lock:
            for attempt in range(_MAX_BROWSER_ATTEMPTS):
                try:
                    return await self._fetch_once(url)
                except _BrowserOperationTimeout as error:
                    if attempt == _MAX_BROWSER_ATTEMPTS - 1:
                        raise BrowserFetchError(str(error)) from None
                    await self._reset_after_timeout(error)
            raise AssertionError("unreachable")

    async def close(self):
        await super().close()
        self._warmed.clear()


__all__ = [
    "BrowserFetchError",
    "BrowserFetcher",
    "CHALLENGE_DETECTORS",
    "is_challenge_page",
    "is_cloudflare_challenge",
    "is_imperva_challenge",
    "loopnet_block_reason",
]
