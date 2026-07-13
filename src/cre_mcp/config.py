"""Configuration for the CRE deal-intelligence MCP server."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_aliases(field_name: str) -> AliasChoices:
    """Accept current CRE variables and their legacy LoopNet equivalents."""
    suffix = field_name.upper()
    return AliasChoices(f"CRE_{suffix}", f"LOOPNET_{suffix}")


class CreConfig(BaseSettings):
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
    cache_db_path: Path = Field(
        default=Path.home() / ".cache" / "cre_mcp" / "cache.db",
        validation_alias=_env_aliases("cache_db_path"),
    )

    model_config = SettingsConfigDict(env_prefix="CRE_", populate_by_name=True)


# Backward-compatible name retained for existing callers.
LoopnetConfig = CreConfig
