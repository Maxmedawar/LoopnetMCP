"""Policy-driven asynchronous HTTP client."""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession, RequestsError

from cre_mcp.cache import Cache, SQLiteCache, TTLCache
from cre_mcp.config import CreConfig
from cre_mcp.http.errors import (
    FetchBlockedError,
    FetchClientError,
    FetchRateLimitError,
)
from cre_mcp.http.policies import (
    POLICY_REGISTRY,
    FetchPolicy,
    build_arcgis_policies,
    build_auctioncom_policies,
    build_crexi_policy,
    build_gov_policies,
    build_loopnet_policy,
)

logger = logging.getLogger(__name__)


class FetchClient:
    """Async HTTP client with per-host policies, rate limits, retries, and caching."""

    def __init__(
        self,
        config: CreConfig | None = None,
        cache: Cache | None = None,
        persistent_cache: SQLiteCache | None = None,
        policies: Mapping[str, FetchPolicy] | None = None,
    ):
        self._config = config or CreConfig()
        self._cache = cache or TTLCache(
            ttl_seconds=self._config.cache_ttl_seconds,
            max_entries=self._config.cache_max_entries,
        )
        self._persistent_cache = persistent_cache or SQLiteCache(
            self._config.cache_db_path
        )

        self._policies = dict(POLICY_REGISTRY)
        self._policies["www.loopnet.com"] = build_loopnet_policy(self._config)
        self._policies["api.crexi.com"] = build_crexi_policy(self._config)
        self._policies.update(build_auctioncom_policies(self._config))
        self._policies.update(build_arcgis_policies(self._config))
        self._policies.update(build_gov_policies(self._config))
        if policies is not None:
            self._policies.update(policies)

        self._semaphores: dict[str, asyncio.Semaphore] = {
            host: asyncio.Semaphore(self._config.max_concurrent_requests)
            for host in self._policies
        }
        self._last_request_time: dict[str, float] = {}
        self._clients: dict[str, AsyncSession] = {}
        self._warmed_up_hosts: set[str] = set()
        self._browser_fetcher = None

        # Compatibility attributes retained for callers that inspected the old client.
        self._semaphore = self._semaphores["www.loopnet.com"]
        self._client: AsyncSession | None = None
        self._warmed_up: bool = False

    def _policy_for_url(self, url: str) -> FetchPolicy:
        host = urlparse(url).hostname
        if not host:
            raise FetchClientError(f"URL has no host: {url}")
        return self._policies.get(
            host,
            FetchPolicy(
                host=host,
                delay_seconds=0.0,
                max_retries=self._config.max_retries,
                impersonate=None,
                browser_fallback=False,
                cache_ttl_seconds=self._config.cache_ttl_seconds,
            ),
        )

    def _session_class(self):
        """Return the session class; isolated for the legacy patch point."""
        return AsyncSession

    def _get_client(self, policy: FetchPolicy | None = None) -> AsyncSession:
        policy = policy or self._policies["www.loopnet.com"]
        if policy.host not in self._clients:
            kwargs: dict[str, Any] = {
                "timeout": self._config.timeout_seconds,
                "allow_redirects": True,
            }
            if policy.impersonate is not None:
                kwargs["impersonate"] = policy.impersonate
            if policy.default_headers:
                kwargs["headers"] = policy.default_headers
            self._clients[policy.host] = self._session_class()(**kwargs)
        client = self._clients[policy.host]
        if policy.host == "www.loopnet.com":
            self._client = client
        return client

    def _semaphore_for(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(
                self._config.max_concurrent_requests
            )
        return self._semaphores[host]

    async def _enforce_rate_limit(self, policy: FetchPolicy | None = None) -> None:
        policy = policy or self._policies["www.loopnet.com"]
        elapsed = time.monotonic() - self._last_request_time.get(policy.host, 0.0)
        delay = policy.delay_seconds - elapsed
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_request_time[policy.host] = time.monotonic()

    async def _warmup(self, policy: FetchPolicy | None = None) -> None:
        """Hit a policy's warmup URL first to establish cookies/session."""
        policy = policy or self._policies["www.loopnet.com"]
        if policy.warmup_url is None:
            return
        if policy.host in self._warmed_up_hosts:
            return
        if policy.host == "www.loopnet.com" and self._warmed_up:
            self._warmed_up_hosts.add(policy.host)
            return

        self._warmed_up_hosts.add(policy.host)
        if policy.host == "www.loopnet.com":
            self._warmed_up = True
        client = self._get_client(policy)
        try:
            await client.get(policy.warmup_url)
        except RequestsError:
            pass  # Best effort — don't fail if warmup fails
        await asyncio.sleep(1.0)

    @staticmethod
    def _stable_hash(body: Any) -> str:
        if body is None:
            payload = b""
        else:
            try:
                serialized = json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except TypeError:
                serialized = repr(body)
            payload = serialized.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _cache_key(
        self,
        policy: FetchPolicy,
        method: str,
        url: str,
        body: Any = None,
    ) -> str:
        return (
            f"{policy.cache_namespace}:v1:{method.upper()}:{url}:"
            f"{self._stable_hash(body)}"
        )

    @staticmethod
    def _cache_ttl(policy: FetchPolicy, method: str) -> int:
        if method.upper() == "GET" and policy.detail_cache_ttl_seconds is not None:
            return policy.detail_cache_ttl_seconds
        return policy.cache_ttl_seconds

    async def _cache_response(
        self,
        key: str,
        value: str,
        policy: FetchPolicy,
        method: str,
    ) -> None:
        self._cache.set(
            key,
            value,
            ttl_seconds=self._cache_ttl(policy, method),
        )
        if policy.persist:
            try:
                await self._persistent_cache.set(
                    key,
                    value,
                    ttl_seconds=self._cache_ttl(policy, method),
                )
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                logger.warning("Persistent cache write failed for %s: %s", key, exc)

    async def _cached_response(
        self,
        key: str,
        policy: FetchPolicy,
        method: str,
    ) -> str | None:
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if not policy.persist:
            return None
        try:
            persisted = await self._persistent_cache.get(key)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            logger.warning("Persistent cache read failed for %s: %s", key, exc)
            return None
        if persisted is not None:
            self._cache.set(
                key,
                persisted,
                ttl_seconds=self._cache_ttl(policy, method),
            )
        return persisted

    async def get_text(self, url: str) -> str:
        return await self._request_text("GET", url)

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        body: Any = None,
        expects_json: bool = False,
        headers: Mapping[str, str] | None = None,
        body_encoding: str = "json",
    ) -> str:
        """Run any request through the shared policy, cache, and retry path."""
        policy = self._policy_for_url(url)
        method = method.upper()
        cache_body = (
            body
            if body_encoding == "json"
            else {"body_encoding": body_encoding, "body": body}
        )
        cache_key = self._cache_key(policy, method, url, cache_body)
        cached = await self._cached_response(cache_key, policy, method)
        if cached is not None:
            return cached

        await self._warmup(policy)

        async with self._semaphore_for(policy.host):
            # Double-check cache after acquiring the host semaphore.
            cached = await self._cached_response(cache_key, policy, method)
            if cached is not None:
                return cached
            return await self._fetch_with_retries(
                url,
                policy,
                cache_key,
                method=method,
                body=body,
                expects_json=expects_json,
                headers=headers,
                body_encoding=body_encoding,
            )

    async def fetch(self, url: str) -> str:
        """Backward-compatible alias for ``get_text``."""
        return await self.get_text(url)

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Fetch and decode a JSON response through the per-host policy path."""
        text = await self._request_text(
            "GET", url, expects_json=True, headers=headers
        )
        return self._decode_json(text, url)

    async def post_json(
        self,
        url: str,
        body: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST a JSON body and decode the response through the shared policy path."""
        text = await self._request_text(
            "POST",
            url,
            body=body,
            expects_json=True,
            headers=headers,
        )
        return self._decode_json(text, url)

    async def post_form_json(
        self,
        url: str,
        body: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST form-encoded data and decode JSON through the policy/cache path."""
        text = await self._request_text(
            "POST",
            url,
            body=body,
            expects_json=True,
            headers=headers,
            body_encoding="form",
        )
        return self._decode_json(text, url)

    @staticmethod
    def _decode_json(text: str, url: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchClientError(
                f"Invalid JSON response for URL: {url}: {exc.msg}"
            ) from exc

    async def _fetch_with_retries(
        self,
        url: str,
        policy: FetchPolicy | None = None,
        cache_key: str | None = None,
        *,
        method: str = "GET",
        body: Any = None,
        expects_json: bool = False,
        headers: Mapping[str, str] | None = None,
        body_encoding: str = "json",
    ) -> str:
        policy = policy or self._policy_for_url(url)
        method = method.upper()
        cache_key = cache_key or self._cache_key(policy, method, url, body)
        client = self._get_client(policy)
        last_error: Exception | None = None
        source_name = "Loopnet" if policy.host == "www.loopnet.com" else policy.host

        for attempt in range(policy.max_retries):
            await self._enforce_rate_limit(policy)
            try:
                if method == "GET":
                    if headers:
                        response = await client.get(url, headers=dict(headers))
                    else:
                        response = await client.get(url)
                elif method == "POST":
                    request_body = (
                        {"data": body}
                        if body_encoding == "form"
                        else {"json": body}
                    )
                    if headers:
                        response = await client.post(
                            url,
                            **request_body,
                            headers=dict(headers),
                        )
                    else:
                        response = await client.post(url, **request_body)
                else:
                    raise FetchClientError(f"Unsupported HTTP method: {method}")

                if response.status_code == 200:
                    text = response.text
                    detector = policy.challenge_detector
                    if detector is not None and detector(text):
                        logger.info(
                            "Challenge page detected for %s, falling back to browser",
                            url,
                        )
                        return await self._fetch_with_browser(
                            url,
                            policy,
                            cache_key,
                            method=method,
                            body=body,
                            expects_json=expects_json,
                        )
                    await self._cache_response(cache_key, text, policy, method)
                    return text

                text = response.text
                detector = policy.challenge_detector
                if (
                    response.status_code in {403, 503}
                    and detector is not None
                    and detector(text)
                ):
                    logger.info(
                        "Challenge response detected for %s, falling back to browser",
                        url,
                    )
                    return await self._fetch_with_browser(
                        url,
                        policy,
                        cache_key,
                        method=method,
                        body=body,
                        expects_json=expects_json,
                    )

                if response.status_code == 403:
                    last_error = FetchBlockedError(
                        f"Blocked by {source_name} (403) for URL: {url}"
                    )
                elif response.status_code == 429:
                    last_error = FetchRateLimitError(
                        f"Rate limited (429) for URL: {url}"
                    )
                elif response.status_code >= 500:
                    last_error = FetchClientError(
                        f"Server error ({response.status_code}) for URL: {url}"
                    )
                else:
                    raise FetchClientError(
                        f"Unexpected status {response.status_code} for URL: {url}"
                    )

            except RequestsError as exc:
                last_error = FetchClientError(
                    f"Request failed for URL: {url}: {exc}"
                )

            if attempt < policy.max_retries - 1:
                await asyncio.sleep(2**attempt)

        raise last_error  # type: ignore[misc]

    async def _fetch_with_browser(
        self,
        url: str,
        policy: FetchPolicy | None = None,
        cache_key: str | None = None,
        *,
        method: str = "GET",
        body: Any = None,
        expects_json: bool = False,
    ) -> str:
        """Fall back to a browser to solve JavaScript challenges."""
        policy = policy or self._policy_for_url(url)
        if not policy.browser_fallback or not self._config.browser_enabled:
            raise FetchClientError(
                f"Challenge page detected but browser fallback is disabled for URL: {url}"
            )

        from cre_mcp.http.browser import BrowserFetcher

        if self._browser_fetcher is None:
            self._browser_fetcher = BrowserFetcher(self._config)

        if expects_json:
            text = await self._browser_fetcher.fetch_api(
                url,
                method=method,
                body=body,
                warmup_url=policy.warmup_url or "https://www.crexi.com/",
            )
        else:
            text = await self._browser_fetcher.fetch(url)
        await self._cache_response(
            cache_key or self._cache_key(policy, method, url, body),
            text,
            policy,
            method,
        )
        return text

    async def close(self) -> None:
        if self._browser_fetcher is not None:
            await self._browser_fetcher.close()
            self._browser_fetcher = None

        seen: set[int] = set()
        for client in self._clients.values():
            if id(client) not in seen:
                await client.close()
                seen.add(id(client))
        self._clients.clear()
        self._client = None

    async def __aenter__(self) -> "FetchClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


_singleton: FetchClient | None = None


def get_fetch_client() -> FetchClient:
    """Return the module-level shared FetchClient."""
    global _singleton
    if _singleton is None:
        _singleton = FetchClient()
    return _singleton


__all__ = [
    "FetchBlockedError",
    "FetchClient",
    "FetchClientError",
    "FetchRateLimitError",
    "get_fetch_client",
]
