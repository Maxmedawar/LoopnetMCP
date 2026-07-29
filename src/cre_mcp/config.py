"""Configuration for the CRE deal-intelligence MCP server."""

from pathlib import Path
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from cre_mcp.access.profiles import Profile


def _env_aliases(field_name: str) -> AliasChoices:
    """Accept current CRE variables and their legacy LoopNet equivalents."""
    suffix = field_name.upper()
    return AliasChoices(f"CRE_{suffix}", f"LOOPNET_{suffix}")


class SourceToggle(BaseModel):
    """Enable or disable one configured listing source."""

    enabled: bool = True


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
            "loopnet": SourceToggle(enabled=True),
            "crexi": SourceToggle(enabled=True),
            "hud_reo": SourceToggle(enabled=True),
            "auction_com": SourceToggle(enabled=True),
            "county": SourceToggle(enabled=True),
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
    stripe_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("stripe_webhook_secret"),
    )
    skool_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias=_env_aliases("skool_webhook_secret"),
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

    @field_validator("stripe_webhook_secret", "skool_webhook_secret")
    @classmethod
    def blank_secret_is_unconfigured(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        return value if value.get_secret_value().strip() else None

    @field_validator("stripe_price_mappings")
    @classmethod
    def validate_stripe_mapping_keys(
        cls,
        value: dict[str, ProviderPlanMapping],
    ) -> dict[str, ProviderPlanMapping]:
        if any(not key.strip() for key in value):
            raise ValueError("Stripe price ids cannot be blank")
        return value

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
