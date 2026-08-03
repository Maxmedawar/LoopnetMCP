"""Policy-driven asynchronous HTTP client."""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from curl_cffi.requests import AsyncSession, RequestsError
from pydantic import SecretStr

from cre_mcp.access.context import current_runtime_config
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
from cre_mcp.source_rights.gate import (
    SourceRightsDeniedError,
    is_hosted_execution,
    require_url,
)
from cre_mcp.source_rights.output import (
    GENERIC_CREDENTIAL_NAMES,
    canonicalize_for_cache,
    redact_url,
    safe_error_message,
)
from cre_mcp.source_rights.registry import (
    SourceRightsRegistryError,
    get_rights_registry,
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
            host: asyncio.Semaphore(policy.max_concurrency)
            for host, policy in self._policies.items()
        }
        self._semaphore_limits: dict[str, int] = {
            host: policy.max_concurrency
            for host, policy in self._policies.items()
        }
        self._last_request_time: dict[str, float] = {}
        self._clients: dict[str, AsyncSession] = {}
        self._warmed_up_hosts: set[str] = set()
        self._browser_fetcher = None

        # Compatibility attributes retained for callers that inspected the old client.
        self._semaphore = self._semaphores["www.loopnet.com"]
        self._client: AsyncSession | None = None
        self._warmed_up: bool = False
        self._secret_values = tuple(
            value.get_secret_value()
            for field_name in type(self._config).model_fields
            if isinstance((value := getattr(self._config, field_name, None)), SecretStr)
            and value.get_secret_value()
        )

    def _runtime_bound_client(self) -> "FetchClient":
        """Route long-lived providers through the active server configuration."""
        runtime = current_runtime_config()
        if runtime is None or runtime is self._config:
            return self
        return get_fetch_client(runtime)

    def _safe_url(self, url: str) -> str:
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return runtime_client._safe_url(url)
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

    def _policy_for_url(self, url: str, *, method: str = "GET") -> FetchPolicy:
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return runtime_client._policy_for_url(url, method=method)
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            parsed.port  # Force validation of a malformed port before diagnostics.
        except (TypeError, ValueError):
            raise FetchClientError("URL is invalid") from None
        if parsed.scheme.casefold() not in {"http", "https"} or not host:
            raise FetchClientError("URL is invalid or has no host")
        try:
            record = require_url(url, method=method, config=self._config)
        except SourceRightsDeniedError as exc:
            raise FetchClientError(str(exc)) from exc
        base_policy = self._policies.get(
            host,
            FetchPolicy(
                host=host,
                delay_seconds=max(self._config.request_delay_seconds, 1.0),
                max_concurrency=1,
                max_retries=self._config.max_retries,
                impersonate=None,
                browser_fallback=False,
                cache_ttl_seconds=0,
                detail_cache_ttl_seconds=0,
                persistent_cache_ttl_seconds=0,
                persist=False,
            ),
        )
        if record is None:
            self._configure_policy_semaphore(base_policy)
            return base_policy
        operating = record.operating_policy
        resolved_policy = replace(
            base_policy,
            delay_seconds=operating.delay_seconds,
            max_concurrency=operating.max_concurrency,
            cache_ttl_seconds=operating.memory_cache_ttl_seconds,
            detail_cache_ttl_seconds=operating.memory_cache_ttl_seconds,
            persistent_cache_ttl_seconds=(
                operating.persistent_cache_ttl_seconds
            ),
            persist=operating.persistent_cache_ttl_seconds > 0,
        )
        self._configure_policy_semaphore(resolved_policy)
        return resolved_policy

    def _session_class(self):
        """Return the session class; isolated for the legacy patch point."""
        return AsyncSession

    def _get_client(self, policy: FetchPolicy | None = None) -> AsyncSession:
        policy = policy or self._policies["www.loopnet.com"]
        if policy.host not in self._clients:
            kwargs: dict[str, Any] = {
                "timeout": self._config.timeout_seconds,
                # Redirects are a second egress decision. The caller must submit
                # the destination as a new request so it is classified and gated.
                "allow_redirects": False,
            }
            if policy.impersonate is not None:
                kwargs["impersonate"] = policy.impersonate
            if policy.default_headers:
                kwargs["headers"] = policy.default_headers
            if policy.use_proxy and self._config.proxy_url is not None:
                kwargs["proxy"] = self._config.proxy_url.get_secret_value()
            self._clients[policy.host] = self._session_class()(**kwargs)
        client = self._clients[policy.host]
        if policy.host == "www.loopnet.com":
            self._client = client
        return client

    def _semaphore_for(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            policy = self._policies.get(host)
            limit = policy.max_concurrency if policy is not None else 1
            self._semaphores[host] = asyncio.Semaphore(limit)
            self._semaphore_limits[host] = limit
        return self._semaphores[host]

    def _configure_policy_semaphore(self, policy: FetchPolicy) -> None:
        """Make the most restrictive resolved source policy authoritative."""
        target = max(int(policy.max_concurrency), 1)
        current = self._semaphore_limits.get(policy.host)
        if current is not None and current <= target:
            return
        semaphore = asyncio.Semaphore(target)
        self._semaphores[policy.host] = semaphore
        self._semaphore_limits[policy.host] = target
        if policy.host == "www.loopnet.com":
            self._semaphore = semaphore

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
        try:
            try:
                require_url(policy.warmup_url, method="GET", config=self._config)
            except SourceRightsDeniedError as exc:
                raise FetchClientError(str(exc)) from exc
            client = self._get_client(policy)
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
                    canonicalize_for_cache(body),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except TypeError:
                serialized = repr(body)
            payload = serialized.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _credential_partition_fingerprint(
        self,
        url: str,
        body: Any,
        headers: Mapping[str, str] | None,
        extra_names: tuple[str, ...],
    ) -> str:
        """Hash credential material so redaction cannot merge tenant cache entries."""
        digest = hashlib.sha256()
        names = GENERIC_CREDENTIAL_NAMES | {
            item.strip().casefold() for item in extra_names if item.strip()
        }

        def feed(value: object) -> None:
            if isinstance(value, bytes):
                encoded = value
            elif value is None or isinstance(value, (str, bool, int, float)):
                encoded = str(value).encode("utf-8", errors="replace")
            else:
                encoded = (
                    f"{type(value).__module__}.{type(value).__qualname__}"
                ).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)

        def collect(
            value: Any,
            *,
            sensitive: bool = False,
            depth: int = 0,
            active: set[int] | None = None,
        ) -> None:
            if depth >= 16:
                return
            if value is None or isinstance(value, (str, bytes, bool, int, float)):
                if sensitive:
                    feed(value)
                return
            active = active if active is not None else set()
            object_id = id(value)
            if object_id in active:
                return
            if isinstance(value, Mapping):
                active.add(object_id)
                try:
                    for key, item in value.items():
                        key_text = str(key).strip().casefold()
                        item_sensitive = sensitive or key_text in names
                        if item_sensitive:
                            feed(key_text)
                        collect(
                            item,
                            sensitive=item_sensitive,
                            depth=depth + 1,
                            active=active,
                        )
                finally:
                    active.remove(object_id)
                return
            if isinstance(value, (list, tuple, set, frozenset)):
                active.add(object_id)
                try:
                    for item in value:
                        collect(
                            item,
                            sensitive=sensitive,
                            depth=depth + 1,
                            active=active,
                        )
                finally:
                    active.remove(object_id)
                return
            if sensitive:
                feed(value)

        for configured_secret in self._secret_values:
            feed(configured_secret)
        try:
            parsed = urlsplit(url)
            if parsed.username is not None:
                feed(parsed.username)
            if parsed.password is not None:
                feed(parsed.password)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                if key.strip().casefold() in names:
                    feed(key.strip().casefold())
                    feed(value)
        except (TypeError, ValueError):
            feed("invalid-url")
        collect(headers or {})
        collect(body)
        return digest.hexdigest()

    def _cache_key(
        self,
        policy: FetchPolicy,
        method: str,
        url: str,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            runtime_policy = runtime_client._policy_for_url(url, method=method)
            return runtime_client._cache_key(
                runtime_policy,
                method,
                url,
                body,
                headers=headers,
            )
        try:
            record = require_url(url, method=method, config=self._config)
        except SourceRightsDeniedError as exc:
            raise FetchClientError(str(exc)) from exc
        safe_url = redact_url(
            url,
            tuple(record.query_credentials) if record is not None else (),
            secret_values=self._secret_values,
        )
        safe_metadata = canonicalize_for_cache(
            {"body": body, "headers": dict(headers or {})},
            secret_values=self._secret_values,
        )
        credential_partition = self._credential_partition_fingerprint(
            url,
            body,
            headers,
            tuple(record.query_credentials) if record is not None else (),
        )
        policy_partition = self._stable_hash(
            {
                "source_id": record.source_id if record is not None else None,
                "rights_state": (
                    record.rights_state.value if record is not None else None
                ),
                "memory_cache_ttl_seconds": self._cache_ttl(policy, method),
                "persistent_cache_ttl_seconds": self._persistent_cache_ttl(
                    policy,
                    method,
                ),
                "raw_storage_allowed": (
                    record.raw_storage_allowed if record is not None else False
                ),
                "raw_output_allowed": (
                    record.raw_output_allowed if record is not None else False
                ),
            }
        )
        return (
            f"{policy.cache_namespace}:v3:{method.upper()}:{safe_url}:"
            f"{self._stable_hash(safe_metadata)}:{credential_partition}:"
            f"{policy_partition}"
        )

    @staticmethod
    def _cache_ttl(policy: FetchPolicy, method: str) -> int:
        if method.upper() == "GET" and policy.detail_cache_ttl_seconds is not None:
            return policy.detail_cache_ttl_seconds
        return policy.cache_ttl_seconds

    @classmethod
    def _persistent_cache_ttl(cls, policy: FetchPolicy, method: str) -> int:
        configured = policy.persistent_cache_ttl_seconds
        if configured is not None:
            return configured
        return cls._cache_ttl(policy, method) if policy.persist else 0

    async def _cache_response(
        self,
        key: str,
        value: str,
        policy: FetchPolicy,
        method: str,
    ) -> None:
        memory_ttl = self._cache_ttl(policy, method)
        persistent_ttl = self._persistent_cache_ttl(policy, method)
        if memory_ttl <= 0 and persistent_ttl <= 0:
            return
        if memory_ttl > 0:
            self._cache.set(key, value, ttl_seconds=memory_ttl)
        if persistent_ttl > 0:
            try:
                await self._persistent_cache.set(
                    key,
                    value,
                    ttl_seconds=persistent_ttl,
                )
            except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
                logger.warning(
                    "Persistent cache write failed for %s: %s",
                    key,
                    safe_error_message(exc, config=self._config),
                )

    async def _cached_response(
        self,
        key: str,
        policy: FetchPolicy,
        method: str,
    ) -> str | None:
        memory_ttl = self._cache_ttl(policy, method)
        persistent_ttl = self._persistent_cache_ttl(policy, method)
        if memory_ttl <= 0 and persistent_ttl <= 0:
            return None
        if memory_ttl > 0:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        if persistent_ttl <= 0:
            return None
        try:
            persisted = await self._persistent_cache.get(key)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            logger.warning(
                "Persistent cache read failed for %s: %s",
                key,
                safe_error_message(exc, config=self._config),
            )
            return None
        if persisted is not None and memory_ttl > 0:
            self._cache.set(
                key,
                persisted,
                ttl_seconds=memory_ttl,
            )
        return persisted

    async def get_text(self, url: str) -> str:
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return await runtime_client.get_text(url)
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
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return await runtime_client._request_text(
                method,
                url,
                body=body,
                expects_json=expects_json,
                headers=headers,
                body_encoding=body_encoding,
            )
        method = method.upper()
        policy = self._policy_for_url(url, method=method)
        cache_body = (
            body
            if body_encoding == "json"
            else {"body_encoding": body_encoding, "body": body}
        )
        cache_key = self._cache_key(
            policy,
            method,
            url,
            cache_body,
            headers=headers,
        )
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
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return await runtime_client.get_json(url, headers=headers)
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
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return await runtime_client.post_json(url, body, headers=headers)
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
        runtime_client = self._runtime_bound_client()
        if runtime_client is not self:
            return await runtime_client.post_form_json(
                url,
                body,
                headers=headers,
            )
        text = await self._request_text(
            "POST",
            url,
            body=body,
            expects_json=True,
            headers=headers,
            body_encoding="form",
        )
        return self._decode_json(text, url)

    def _decode_json(self, text: str, url: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchClientError(
                "Invalid JSON response for URL: "
                f"{self._safe_url(url)}: {exc.msg}"
            ) from None

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
        method = method.upper()
        policy = policy or self._policy_for_url(url, method=method)
        try:
            require_url(url, method=method, config=self._config)
        except SourceRightsDeniedError as exc:
            raise FetchClientError(str(exc)) from exc
        cache_key = cache_key or self._cache_key(
            policy,
            method,
            url,
            body,
            headers=headers,
        )
        client = self._get_client(policy)
        last_error: Exception | None = None
        source_name = "Loopnet" if policy.host == "www.loopnet.com" else policy.host

        for attempt in range(policy.max_retries):
            await self._enforce_rate_limit(policy)
            try:
                if method == "GET":
                    if headers:
                        response = await client.get(
                            url,
                            headers=dict(headers),
                        )
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
                        response = await client.post(
                            url,
                            **request_body,
                        )
                else:
                    raise FetchClientError(f"Unsupported HTTP method: {method}")

                if response.status_code == 200:
                    text = response.text
                    detector = policy.challenge_detector
                    if detector is not None and detector(text):
                        logger.info(
                            "Challenge page detected for %s, falling back to browser",
                            self._safe_url(url),
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
                        self._safe_url(url),
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
                        "Blocked by "
                        f"{source_name} (403) for URL: "
                        f"{self._safe_url(url)}"
                    )
                elif response.status_code == 429:
                    last_error = FetchRateLimitError(
                        "Rate limited (429) for URL: "
                        f"{self._safe_url(url)}"
                    )
                elif response.status_code >= 500:
                    last_error = FetchClientError(
                        f"Server error ({response.status_code}) for URL: "
                        f"{self._safe_url(url)}"
                    )
                else:
                    raise FetchClientError(
                        f"Unexpected status {response.status_code} for URL: "
                        f"{self._safe_url(url)}"
                    )

            except RequestsError:
                last_error = FetchClientError(
                    f"Request failed for classified source: {source_name}"
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
        policy = policy or self._policy_for_url(url, method=method)
        try:
            require_url(url, method=method, config=self._config)
        except SourceRightsDeniedError as exc:
            raise FetchClientError(str(exc)) from exc
        if is_hosted_execution(self._config):
            raise FetchClientError(
                "source-rights denied: browser fallback cannot prove redirected egress"
            )
        if not policy.browser_fallback or not self._config.browser_enabled:
            raise FetchClientError(
                "Challenge page detected but browser fallback is disabled for URL: "
                f"{self._safe_url(url)}"
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


def get_fetch_client(config: CreConfig | None = None) -> FetchClient:
    """Return a shared client bound to the server-owned runtime configuration."""
    global _singleton
    selected = current_runtime_config() or config
    if _singleton is None or (
        selected is not None and _singleton._config is not selected
    ):
        _singleton = FetchClient(selected)
    return _singleton


__all__ = [
    "FetchBlockedError",
    "FetchClient",
    "FetchClientError",
    "FetchRateLimitError",
    "get_fetch_client",
]
