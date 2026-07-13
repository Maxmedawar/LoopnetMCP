"""Per-host fetch behavior."""

from collections.abc import Callable
from dataclasses import dataclass, field

from cre_mcp.config import CreConfig
from cre_mcp.http.browser import is_challenge_page


@dataclass(frozen=True)
class FetchPolicy:
    host: str
    delay_seconds: float = 3.0
    max_retries: int = 3
    impersonate: str | None = "chrome136"
    warmup_url: str | None = None
    challenge_detector: Callable[[str], bool] | None = None
    browser_fallback: bool = False
    default_headers: dict[str, str] = field(default_factory=dict)
    cache_namespace: str = "http"
    cache_ttl_seconds: int = 300
    persist: bool = False


def build_loopnet_policy(config: CreConfig | None = None) -> FetchPolicy:
    """Build the LoopNet policy from current configuration."""
    config = config or CreConfig()
    return FetchPolicy(
        host="www.loopnet.com",
        delay_seconds=config.request_delay_seconds,
        max_retries=config.max_retries,
        impersonate=config.impersonate_browser,
        warmup_url=config.base_url,
        challenge_detector=is_challenge_page,
        browser_fallback=config.browser_enabled,
        cache_namespace="loopnet",
        cache_ttl_seconds=config.cache_ttl_seconds,
    )


POLICY_REGISTRY: dict[str, FetchPolicy] = {
    "www.loopnet.com": build_loopnet_policy(),
}
