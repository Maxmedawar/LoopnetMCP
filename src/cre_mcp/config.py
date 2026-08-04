"""Configuration for the CRE deal-intelligence MCP server."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from cre_mcp.access.profiles import Profile


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validated_http_url(
    value: str,
    *,
    field_name: str,
    origin_only: bool,
) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field_name} must be an absolute HTTP URL without credentials")
    if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(f"{field_name} must use HTTPS outside loopback development")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} has an invalid port") from exc
    if parsed.fragment:
        raise ValueError(f"{field_name} cannot include a fragment")
    if origin_only and (parsed.path not in {"", "/"} or parsed.query):
        raise ValueError(f"{field_name} must be an origin without path or query")
    if origin_only:
        return f"{parsed.scheme}://{parsed.netloc}"
    return normalized


def _env_aliases(field_name: str) -> AliasChoices:
    """Accept current CRE variables and their legacy LoopNet equivalents."""
    suffix = field_name.upper()
    return AliasChoices(f"CRE_{suffix}", f"LOOPNET_{suffix}")


class SourceToggle(BaseModel):
    """Enable or disable one configured listing source."""

    enabled: bool = False


class ProviderPlanMapping(BaseModel):
    """One server-owned provider tier to platform entitlement mapping."""

    plan_key: str
    profile: Profile

    @field_validator("plan_key")
    @classmethod
    def validate_plan_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("plan_key cannot be blank")
        return normalized


class CreConfig(BaseSettings):
    transport: Literal["stdio", "http"] = Field(
        default="stdio",
        validation_alias=_env_aliases("transport"),
    )
    http_host: str = Field(
        default="0.0.0.0",
        validation_alias=_env_aliases("http_host"),
    )
    http_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias=_env_aliases("http_port"),
    )
    oauth_audience: str = Field(
        default="medawarcre-mcp",
        validation_alias=_env_aliases("oauth_audience"),
    )
    oauth_resource: str = Field(
        default="https://mcp.medawarcre.com/mcp",
        validation_alias=_env_aliases("oauth_resource"),
    )
    oauth_refresh_family_max_age_days: int = Field(
        default=90,
        ge=1,
        validation_alias=_env_aliases("oauth_refresh_family_max_age_days"),
    )
    oauth_issuer: str = Field(
        default="http://localhost:8000",
        validation_alias=_env_aliases("oauth_issuer"),
    )
    connection_url: str = Field(
        default="http://localhost:5173/connect",
        validation_alias=_env_aliases("connection_url"),
    )
    human_identity_provider: Literal["disabled", "clerk"] = Field(
        default="disabled",
        validation_alias=_env_aliases("human_identity_provider"),
    )
    clerk_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("clerk_secret_key"),
    )
    clerk_publishable_key: str | None = Field(
        default=None,
        validation_alias=_env_aliases("clerk_publishable_key"),
    )
    clerk_authorized_parties: tuple[str, ...] = Field(
        default=(),
        validation_alias=_env_aliases("clerk_authorized_parties"),
    )
    clerk_issuer: str | None = Field(
        default=None,
        validation_alias=_env_aliases("clerk_issuer"),
    )
    browser_session_ttl_seconds: int = Field(
        default=30 * 60,
        ge=60,
        le=24 * 60 * 60,
        validation_alias=_env_aliases("browser_session_ttl_seconds"),
    )
    browser_cookie_name: str = Field(
        default="mcr_browser",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        validation_alias=_env_aliases("browser_cookie_name"),
    )
    browser_cookie_secure: bool = Field(
        default=True,
        validation_alias=_env_aliases("browser_cookie_secure"),
    )
    operations_console_origin: str | None = Field(
        default=None,
        validation_alias=_env_aliases("operations_console_origin"),
    )
    operations_session_ttl_seconds: int = Field(
        default=30 * 60,
        ge=60,
        le=8 * 60 * 60,
        validation_alias=_env_aliases("operations_session_ttl_seconds"),
    )
    operations_cookie_name: str = Field(
        default="mcr_ops",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        validation_alias=_env_aliases("operations_cookie_name"),
    )
    request_delay_seconds: float = Field(
        default=3.0,
        validation_alias=_env_aliases("request_delay_seconds"),
    )
    max_concurrent_requests: int = Field(
        default=1,
        validation_alias=_env_aliases("max_concurrent_requests"),
    )
    timeout_seconds: float = Field(
        default=30.0,
        validation_alias=_env_aliases("timeout_seconds"),
    )
    max_retries: int = Field(
        default=3,
        validation_alias=_env_aliases("max_retries"),
    )
    impersonate_browser: str = Field(
        default="chrome136",
        validation_alias=_env_aliases("impersonate_browser"),
    )
    cache_ttl_seconds: int = Field(
        default=300,
        validation_alias=_env_aliases("cache_ttl_seconds"),
    )
    cache_max_entries: int = Field(
        default=500,
        validation_alias=_env_aliases("cache_max_entries"),
    )
    base_url: str = Field(
        default="https://www.loopnet.com",
        validation_alias=_env_aliases("base_url"),
    )
    browser_enabled: bool = Field(
        default=True,
        validation_alias=_env_aliases("browser_enabled"),
    )
    browser_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=_env_aliases("browser_timeout_seconds"),
    )
    browser_challenge_wait_seconds: float = Field(
        default=5.0,
        validation_alias=_env_aliases("browser_challenge_wait_seconds"),
    )
    browser_headless: bool = Field(
        default=True,
        validation_alias=_env_aliases("browser_headless"),
    )
    browser_path: Path | None = Field(
        default=None,
        validation_alias=_env_aliases("browser_path"),
    )
    proxy_url: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("proxy_url"),
    )
    sources: dict[str, SourceToggle] = Field(
        default_factory=lambda: {
            "loopnet": SourceToggle(enabled=False),
            "crexi": SourceToggle(enabled=False),
            "hud_reo": SourceToggle(enabled=False),
            "auction_com": SourceToggle(enabled=False),
            "county": SourceToggle(enabled=False),
        },
        validation_alias=_env_aliases("sources"),
    )

    census_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("census_api_key"),
    )
    bls_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("bls_api_key"),
    )
    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("fred_api_key"),
    )
    hud_api_token: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("hud_api_token"),
    )
    bea_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("bea_api_key"),
    )
    rentcast_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("rentcast_api_key"),
    )
    skiptrace_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("skiptrace_api_key"),
    )
    attom_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("attom_api_key"),
    )
    regrid_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("regrid_api_key"),
    )
    socrata_app_token: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("socrata_app_token"),
    )
    cache_db_path: Path = Field(
        default=Path.home() / ".cache" / "cre_mcp" / "cache.db",
        validation_alias=_env_aliases("cache_db_path"),
    )
    access_registry_path: Path | None = Field(
        default=None,
        validation_alias=_env_aliases("access_registry_path"),
    )
    access_audit_path: Path | None = Field(
        default=None,
        validation_alias=_env_aliases("access_audit_path"),
    )
    source_rights_registry_path: Path | None = Field(
        default=None,
        validation_alias=_env_aliases("source_rights_registry_path"),
    )
    source_rights_attestations_path: Path | None = Field(
        default=None,
        validation_alias=_env_aliases("source_rights_attestations_path"),
    )
    source_rights_enabled: dict[str, bool] = Field(
        default_factory=dict,
        validation_alias=_env_aliases("source_rights_enabled"),
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("stripe_webhook_secret"),
    )
    stripe_webhook_secrets: tuple[SecretStr, ...] = Field(
        default=(),
        validation_alias=_env_aliases("stripe_webhook_secrets"),
    )
    stripe_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("stripe_api_key"),
    )
    stripe_api_version: str = Field(
        default="2026-02-25.clover",
        validation_alias=_env_aliases("stripe_api_version"),
    )
    skool_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("skool_webhook_secret"),
    )
    skool_webhook_secrets: tuple[SecretStr, ...] = Field(
        default=(),
        validation_alias=_env_aliases("skool_webhook_secrets"),
    )
    skool_reconciliation_max_age_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60,
        le=7 * 24 * 60 * 60,
        validation_alias=_env_aliases("skool_reconciliation_max_age_seconds"),
    )
    skool_community_urls: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=_env_aliases("skool_community_urls"),
    )
    provider_webhook_max_body_bytes: int = Field(
        default=64 * 1024,
        ge=1,
        le=64 * 1024,
        validation_alias=_env_aliases("provider_webhook_max_body_bytes"),
    )
    provider_grant_lease_seconds: int = Field(
        default=24 * 60 * 60,
        ge=1,
        le=7 * 24 * 60 * 60,
        validation_alias=_env_aliases("provider_grant_lease_seconds"),
    )
    stripe_price_mappings: dict[str, ProviderPlanMapping] = Field(
        default_factory=dict,
        validation_alias=_env_aliases("stripe_price_mappings"),
    )
    skool_tier_mappings: dict[str, ProviderPlanMapping] = Field(
        default_factory=dict,
        validation_alias=_env_aliases("skool_tier_mappings"),
    )

    @field_validator(
        "clerk_secret_key",
        "stripe_webhook_secret",
        "stripe_api_key",
        "skool_webhook_secret",
    )
    @classmethod
    def blank_secret_is_unconfigured(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        return value if value.get_secret_value().strip() else None

    @field_validator("stripe_webhook_secrets")
    @classmethod
    def normalize_stripe_webhook_secrets(
        cls,
        value: tuple[SecretStr, ...],
    ) -> tuple[SecretStr, ...]:
        result: list[SecretStr] = []
        seen: set[str] = set()
        for secret in value:
            normalized = secret.get_secret_value().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(SecretStr(normalized))
        return tuple(result)

    @field_validator("skool_webhook_secrets")
    @classmethod
    def normalize_skool_webhook_secrets(
        cls,
        value: tuple[SecretStr, ...],
    ) -> tuple[SecretStr, ...]:
        result: list[SecretStr] = []
        seen: set[str] = set()
        for secret in value:
            normalized = secret.get_secret_value().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(SecretStr(normalized))
        return tuple(result)

    @field_validator("stripe_api_key")
    @classmethod
    def stripe_api_key_must_be_test_mode(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        normalized = value.get_secret_value().strip()
        if not normalized.startswith(("sk_test_", "rk_test_")):
            raise ValueError("stripe_api_key must be a test-mode secret or restricted key")
        return SecretStr(normalized)

    @field_validator("stripe_api_version")
    @classmethod
    def validate_stripe_api_version(cls, value: str) -> str:
        normalized = value.strip()
        date, separator, channel = normalized.partition(".")
        if (
            not separator
            or len(date) != 10
            or date[4] != "-"
            or date[7] != "-"
            or not date.replace("-", "").isdigit()
            or not channel.isascii()
            or not channel.isalpha()
        ):
            raise ValueError("stripe_api_version must be YYYY-MM-DD.channel")
        return normalized

    @field_validator(
        "clerk_publishable_key",
        "clerk_issuer",
        "operations_console_origin",
    )
    @classmethod
    def blank_clerk_text_is_unconfigured(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("oauth_issuer")
    @classmethod
    def validate_oauth_issuer(cls, value: str) -> str:
        return _validated_http_url(
            value,
            field_name="oauth_issuer",
            origin_only=True,
        )

    @field_validator("connection_url")
    @classmethod
    def validate_connection_url(cls, value: str) -> str:
        return _validated_http_url(
            value,
            field_name="connection_url",
            origin_only=False,
        )

    @field_validator("clerk_issuer")
    @classmethod
    def validate_clerk_issuer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_http_url(
            value,
            field_name="clerk_issuer",
            origin_only=True,
        )

    @field_validator("operations_console_origin")
    @classmethod
    def validate_operations_console_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_http_url(
            value,
            field_name="operations_console_origin",
            origin_only=True,
        )

    @field_validator("clerk_authorized_parties")
    @classmethod
    def validate_clerk_authorized_parties(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(
            dict.fromkeys(
                _validated_http_url(
                    item,
                    field_name="clerk_authorized_parties",
                    origin_only=True,
                )
                for item in value
            )
        )
        return normalized

    @field_validator("stripe_price_mappings")
    @classmethod
    def validate_stripe_mapping_keys(
        cls,
        value: dict[str, ProviderPlanMapping],
    ) -> dict[str, ProviderPlanMapping]:
        if any(not key.strip() for key in value):
            raise ValueError("Stripe price ids cannot be blank")
        return value

    @property
    def stripe_signing_secrets(self) -> tuple[SecretStr, ...]:
        """All active test webhook secrets, deduplicated for safe rotation."""
        values: list[SecretStr] = []
        seen: set[str] = set()
        for secret in (
            *((self.stripe_webhook_secret,) if self.stripe_webhook_secret else ()),
            *self.stripe_webhook_secrets,
        ):
            raw = secret.get_secret_value()
            if raw not in seen:
                seen.add(raw)
                values.append(secret)
        return tuple(values)

    @property
    def skool_signing_secrets(self) -> tuple[SecretStr, ...]:
        """All active relay secrets, deduplicated for safe rotation."""
        values: list[SecretStr] = []
        seen: set[str] = set()
        for secret in (
            *((self.skool_webhook_secret,) if self.skool_webhook_secret else ()),
            *self.skool_webhook_secrets,
        ):
            raw = secret.get_secret_value()
            if raw not in seen:
                seen.add(raw)
                values.append(secret)
        return tuple(values)

    @field_validator("skool_tier_mappings")
    @classmethod
    def validate_skool_mapping_keys(
        cls,
        value: dict[str, ProviderPlanMapping],
    ) -> dict[str, ProviderPlanMapping]:
        for key in value:
            community, separator, level = key.partition(":")
            if not separator or not community.strip() or not level.strip():
                raise ValueError(
                    "Skool mapping keys must be <community_id>:<level_id>"
                )
        return value

    @field_validator("skool_community_urls")
    @classmethod
    def validate_skool_community_urls(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for community_id, url in value.items():
            key = community_id.strip()
            if not key or ":" in key or len(key) > 255:
                raise ValueError(
                    "Skool community ids must be nonblank safe identifiers"
                )
            validated = _validated_http_url(
                url,
                field_name="skool_community_urls",
                origin_only=False,
            )
            parsed = urlsplit(validated)
            if parsed.hostname not in {"skool.com", "www.skool.com"}:
                raise ValueError("Skool community URLs must use skool.com")
            normalized[key] = validated
        return normalized

    def model_post_init(self, __context) -> None:
        super().model_post_init(__context)
        # Workspace-scoped storage: when a tool call runs under a cloud tenant
        # context, every store constructed from this config lands in that
        # workspace's own database. The trusted local workspace (and any code
        # outside a request) keeps the configured path untouched.
        try:
            from cre_mcp.access.context import current_context
            from cre_mcp.access.storage import workspace_db_path
        except ImportError:
            return
        ctx = current_context()
        if ctx is not None and not ctx.trusted:
            self.cache_db_path = workspace_db_path(ctx, self.cache_db_path)

    model_config = SettingsConfigDict(
        env_prefix="CRE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


# Backward-compatible name retained for existing callers.
LoopnetConfig = CreConfig


def default_cache_db_path() -> Path:
    """The resolved default cache-database path for the active context.

    Single source of the "db_path or the configured default" resolution shared
    by every per-table store. Honors workspace scoping: inside a cloud tenant's
    tool call this is that workspace's database (via CreConfig.model_post_init);
    elsewhere it is the configured base path.
    """
    return Path(CreConfig().cache_db_path).expanduser()
