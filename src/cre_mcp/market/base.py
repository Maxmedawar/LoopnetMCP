"""Shared government API authentication and provider abstractions."""

from abc import ABC
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, SecretStr

from cre_mcp.http.fetch import FetchClient, get_fetch_client


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot run, usually because credentials are absent."""


class AuthSpec(BaseModel):
    """Declarative API authentication configuration."""

    kind: Literal["none", "query_param", "bearer", "body_field"] = "none"
    param_name: str | None = None
    secret: str | SecretStr | None = None

    def secret_value(self) -> str | None:
        if isinstance(self.secret, SecretStr):
            return self.secret.get_secret_value()
        return self.secret


class GovApiClient:
    """Inject heterogeneous auth and route government traffic through FetchClient."""

    def __init__(self, fetch: FetchClient, auth: AuthSpec, base_url: str):
        self.fetch = fetch
        self.auth = auth
        self.base_url = base_url.rstrip("/") + "/"

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(self.base_url, path.lstrip("/"))

    @staticmethod
    def _with_query(url: str, params: dict[str, Any]) -> str:
        parts = urlsplit(url)
        query = list(parse_qsl(parts.query, keep_blank_values=True))
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                query.extend((key, str(item)) for item in value)
            else:
                query.append((key, str(value)))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    def _headers(self) -> dict[str, str] | None:
        secret = self.auth.secret_value()
        if self.auth.kind == "bearer" and secret:
            return {"Authorization": f"Bearer {secret}"}
        return None

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        merged = dict(params or {})
        secret = self.auth.secret_value()
        if self.auth.kind == "query_param" and secret:
            merged[self.auth.param_name or "key"] = secret
        url = self._with_query(self._url(path), merged)
        headers = self._headers()
        if headers:
            return await self.fetch.get_json(url, headers=headers)
        return await self.fetch.get_json(url)

    async def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        payload = dict(body or {})
        secret = self.auth.secret_value()
        if self.auth.kind == "body_field" and secret:
            payload[self.auth.param_name or "key"] = secret
        headers = self._headers()
        if headers:
            return await self.fetch.post_json(
                self._url(path), payload, headers=headers
            )
        return await self.fetch.post_json(self._url(path), payload)


class MarketDataProvider(ABC):
    """Base class for normalized government market-data providers."""

    name = "provider"

    def __init__(self, client: GovApiClient):
        self.client = client

    @classmethod
    def with_client(
        cls,
        *,
        fetch: FetchClient | None,
        auth: AuthSpec,
        base_url: str,
    ) -> "MarketDataProvider":
        return cls(GovApiClient(fetch or get_fetch_client(), auth, base_url))
