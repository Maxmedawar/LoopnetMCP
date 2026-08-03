"""Per-host fetch behavior."""

from collections.abc import Callable
from dataclasses import dataclass, field

from cre_mcp.config import CreConfig
from cre_mcp.http.browser import (
    is_challenge_page,
    is_cloudflare_challenge,
    is_imperva_challenge,
)


@dataclass(frozen=True)
class FetchPolicy:
    host: str
    delay_seconds: float = 3.0
    max_concurrency: int = 1
    max_retries: int = 3
    impersonate: str | None = "chrome136"
    warmup_url: str | None = None
    challenge_detector: Callable[[str], bool] | None = None
    browser_fallback: bool = False
    default_headers: dict[str, str] = field(default_factory=dict)
    cache_namespace: str = "http"
    cache_ttl_seconds: int = 300
    detail_cache_ttl_seconds: int | None = None
    persistent_cache_ttl_seconds: int | None = None
    persist: bool = False
    use_proxy: bool = False


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
        use_proxy=True,
        cache_namespace="loopnet",
        cache_ttl_seconds=config.cache_ttl_seconds,
    )


def build_crexi_policy(config: CreConfig | None = None) -> FetchPolicy:
    """Build the Cloudflare-aware policy for Crexi's JSON API."""
    config = config or CreConfig()
    return FetchPolicy(
        host="api.crexi.com",
        delay_seconds=config.request_delay_seconds,
        max_retries=config.max_retries,
        impersonate="chrome136",
        warmup_url="https://www.crexi.com/",
        challenge_detector=is_cloudflare_challenge,
        browser_fallback=config.browser_enabled,
        use_proxy=True,
        default_headers={
            "Origin": "https://www.crexi.com",
            "Referer": "https://www.crexi.com/",
        },
        cache_namespace="crexi",
        cache_ttl_seconds=15 * 60,
        detail_cache_ttl_seconds=2 * 60 * 60,
    )


def build_auctioncom_policies(
    config: CreConfig | None = None,
) -> dict[str, FetchPolicy]:
    """Build anti-bot-aware policies for Auction.com pages and GraphQL."""
    config = config or CreConfig()
    common = {
        "delay_seconds": max(config.request_delay_seconds, 3.0),
        "max_retries": config.max_retries,
        "impersonate": "chrome136",
        "warmup_url": "https://www.auction.com/",
        "challenge_detector": is_imperva_challenge,
        "browser_fallback": config.browser_enabled,
        "default_headers": {
            "Origin": "https://www.auction.com",
            "Referer": "https://www.auction.com/",
        },
        "cache_namespace": "auction-com",
        "cache_ttl_seconds": 30 * 60,
        "detail_cache_ttl_seconds": 6 * 60 * 60,
        "persist": True,
        "use_proxy": True,
    }
    return {
        host: FetchPolicy(host=host, **common)
        for host in ("www.auction.com", "graph.auction.com")
    }


def build_arcgis_policies(config: CreConfig | None = None) -> dict[str, FetchPolicy]:
    """Build low-delay, persistent policies for public ArcGIS hosts."""
    config = config or CreConfig()
    hosts = (
        "services.arcgis.com",
        "services1.arcgis.com",
        "services2.arcgis.com",
        "services3.arcgis.com",
        "services5.arcgis.com",
        "services6.arcgis.com",
        "services7.arcgis.com",
        "services8.arcgis.com",
        "services9.arcgis.com",
        "gcgis.guilfordcountync.gov",
        "dtdapps.codot.gov",
        "gis.fdot.gov",
        "caltrans-gis.dot.ca.gov",
        "taxmaps.traviscountytx.gov",
        "gis.sara-tx.org",
        "gismaps.fultoncountyga.gov",
        "gis.charlottenc.gov",
        "maps.wakegov.com",
        "gis.franklincountyohio.gov",
        "gis.dot.nv.gov",
        "egisp.dot.ga.gov",
    )
    return {
        host: FetchPolicy(
            host=host,
            delay_seconds=0.2,
            max_retries=config.max_retries,
            impersonate=None,
            browser_fallback=False,
            cache_namespace="arcgis",
            cache_ttl_seconds=24 * 60 * 60,
            persist=True,
        )
        for host in hosts
    }


def build_gov_policies(config: CreConfig | None = None) -> dict[str, FetchPolicy]:
    """Build conservative, persistent policies for government data hosts."""
    config = config or CreConfig()
    common = {
        "max_retries": config.max_retries,
        "impersonate": None,
        "browser_fallback": False,
        "persist": True,
    }
    return {
        "api.census.gov": FetchPolicy(
            host="api.census.gov",
            delay_seconds=0.2,
            cache_namespace="census",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "www2.census.gov": FetchPolicy(
            host="www2.census.gov",
            delay_seconds=0.2,
            cache_namespace="census-bps",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "geocoding.geo.census.gov": FetchPolicy(
            host="geocoding.geo.census.gov",
            delay_seconds=0.2,
            cache_namespace="census-geocoder",
            cache_ttl_seconds=90 * 24 * 60 * 60,
            **common,
        ),
        "api.bls.gov": FetchPolicy(
            host="api.bls.gov",
            delay_seconds=0.2,
            cache_namespace="bls",
            cache_ttl_seconds=7 * 24 * 60 * 60,
            **common,
        ),
        "api.stlouisfed.org": FetchPolicy(
            host="api.stlouisfed.org",
            delay_seconds=0.2,
            cache_namespace="fred",
            cache_ttl_seconds=0,
            max_retries=config.max_retries,
            impersonate=None,
            browser_fallback=False,
            persist=False,
        ),
        "www.fhfa.gov": FetchPolicy(
            host="www.fhfa.gov",
            delay_seconds=0.2,
            cache_namespace="fhfa-hpi",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "www.irs.gov": FetchPolicy(
            host="www.irs.gov",
            delay_seconds=0.2,
            cache_namespace="irs-soi-migration",
            cache_ttl_seconds=90 * 24 * 60 * 60,
            **common,
        ),
        "www.huduser.gov": FetchPolicy(
            host="www.huduser.gov",
            delay_seconds=0.5,
            cache_namespace="hud",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "apps.bea.gov": FetchPolicy(
            host="apps.bea.gov",
            delay_seconds=0.2,
            cache_namespace="bea",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "files.zillowstatic.com": FetchPolicy(
            host="files.zillowstatic.com",
            delay_seconds=0.2,
            cache_namespace="zillow-zori",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "overpass-api.de": FetchPolicy(
            host="overpass-api.de",
            delay_seconds=1.0,
            cache_namespace="openstreetmap-overpass",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "overpass.kumi.systems": FetchPolicy(
            host="overpass.kumi.systems",
            delay_seconds=1.0,
            cache_namespace="openstreetmap-overpass",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "api.rentcast.io": FetchPolicy(
            host="api.rentcast.io",
            delay_seconds=0.2,
            cache_namespace="rentcast",
            cache_ttl_seconds=24 * 60 * 60,
            **common,
        ),
        "comptroller.texas.gov": FetchPolicy(
            host="comptroller.texas.gov",
            delay_seconds=0.5,
            cache_namespace="tx-business-registry",
            cache_ttl_seconds=30 * 24 * 60 * 60,
            **common,
        ),
        "api.realestateapi.com": FetchPolicy(
            host="api.realestateapi.com",
            delay_seconds=0.2,
            cache_namespace="skiptrace",
            cache_ttl_seconds=90 * 24 * 60 * 60,
            **common,
        ),
    }


POLICY_REGISTRY: dict[str, FetchPolicy] = {
    "www.loopnet.com": build_loopnet_policy(),
    "api.crexi.com": build_crexi_policy(),
    **build_auctioncom_policies(),
    **build_arcgis_policies(),
    **build_gov_policies(),
}
