"""Backward-compatible LoopNet client exports."""

from curl_cffi.requests import AsyncSession, RequestsError

from cre_mcp.access.context import current_runtime_config
from cre_mcp.cache import Cache
from cre_mcp.config import CreConfig, LoopnetConfig
from cre_mcp.http.errors import (
    FetchBlockedError,
    FetchClientError,
    FetchRateLimitError,
)
from cre_mcp.http.fetch import FetchClient

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

    async def _fetch_with_browser(self, *args, **kwargs) -> str:
        """Use the LoopNet-hardened fetcher and discard blocked sessions."""
        from cre_mcp.scraper.browser import BrowserFetchError, BrowserFetcher

        if self._browser_fetcher is None:
            self._browser_fetcher = BrowserFetcher(self._config)
        try:
            return await super()._fetch_with_browser(*args, **kwargs)
        except BrowserFetchError:
            await self._browser_fetcher.close()
            self._browser_fetcher = None
            raise FetchBlockedError(
                "loopnet_blocked: browser retrieval failed"
            ) from None


_singleton: LoopnetClient | None = None


def get_client(config: LoopnetConfig | None = None) -> LoopnetClient:
    """Return a shared LoopNet client bound to the active runtime config."""
    global _singleton
    selected = current_runtime_config() or config
    if _singleton is None or (
        selected is not None and _singleton._config is not selected
    ):
        _singleton = LoopnetClient(selected)
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
