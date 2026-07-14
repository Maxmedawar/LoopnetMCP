"""Backward-compatible LoopNet client exports."""

from typing import Any

from curl_cffi.requests import AsyncSession, RequestsError

from cre_mcp.cache import Cache
from cre_mcp.config import CreConfig, LoopnetConfig
from cre_mcp.http.errors import (
    FetchBlockedError,
    FetchClientError,
    FetchRateLimitError,
)
from cre_mcp.http.fetch import FetchClient
from cre_mcp.http.policies import FetchPolicy

LoopnetClientError = FetchClientError
LoopnetBlockedError = FetchBlockedError
LoopnetRateLimitError = FetchRateLimitError


class LoopnetClient(FetchClient):
    """Compatibility wrapper exposing the original LoopNet client API."""

    def __init__(
        self,
        config: LoopnetConfig | None = None,
        cache: Cache | None = None,
    ):
        super().__init__(config=config, cache=cache)

    def _session_class(self):
        # Keep ``cre_mcp.scraper.client.AsyncSession`` patchable by old tests/callers.
        return AsyncSession

    def _cache_key(
        self,
        policy: FetchPolicy,
        method: str,
        url: str,
        body: Any = None,
    ) -> str:
        # The legacy client keyed GET text responses directly by URL.
        if method.upper() == "GET" and body is None:
            return url
        return super()._cache_key(policy, method, url, body)

    async def _fetch_with_browser(self, *args, **kwargs) -> str:
        """Use the LoopNet-hardened fetcher and discard blocked sessions."""
        from cre_mcp.scraper.browser import BrowserFetchError, BrowserFetcher

        if self._browser_fetcher is None:
            self._browser_fetcher = BrowserFetcher(self._config)
        try:
            return await super()._fetch_with_browser(*args, **kwargs)
        except BrowserFetchError as exc:
            await self._browser_fetcher.close()
            self._browser_fetcher = None
            message = str(exc)
            if not message.startswith("loopnet_blocked:"):
                message = f"loopnet_blocked: {message}"
            raise FetchBlockedError(message) from exc


_singleton: LoopnetClient | None = None


def get_client() -> LoopnetClient:
    """Return a module-level singleton LoopnetClient."""
    global _singleton
    if _singleton is None:
        _singleton = LoopnetClient()
    return _singleton


__all__ = [
    "AsyncSession",
    "CreConfig",
    "LoopnetBlockedError",
    "LoopnetClient",
    "LoopnetClientError",
    "LoopnetConfig",
    "LoopnetRateLimitError",
    "RequestsError",
    "get_client",
]
