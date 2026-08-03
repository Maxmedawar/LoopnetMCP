"""Cached county parcel lookup and owner derivation."""

import logging
import re
from collections.abc import Awaitable, Callable

from cre_mcp.access.context import resolve_runtime_config
from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.arcgis import ArcgisParcelProvider, county_sales_authorized
from cre_mcp.enrichment.base import ParcelProvider, ProviderUnavailable
from cre_mcp.enrichment.counties import CountyParcelConfig, config_for_geo
from cre_mcp.enrichment.providers.attom import AttomProvider
from cre_mcp.enrichment.providers.regrid import RegridProvider
from cre_mcp.geo.resolver import resolve
from cre_mcp.models.enrichment import OwnerRecord, ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.sources.dedupe import normalize_address
from cre_mcp.source_rights.gate import require_url
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference

_CACHE_TTL_SECONDS = 90 * 24 * 60 * 60
_MISSING = {"missing": True}
logger = logging.getLogger(__name__)

_PAID_RIGHTS_URLS = {
    "attom": "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detailowner",
    "regrid": "https://app.regrid.com/api/v2/parcels/address",
}

PaidProviderFactory = Callable[[CreConfig, SQLiteCache], ParcelProvider]


def _default_paid_provider_factories() -> tuple[PaidProviderFactory, ...]:
    return (
        lambda config, cache: RegridProvider(config, cache=cache),
        lambda config, cache: AttomProvider(config, cache=cache),
    )


def _secret_is_set(secret: object) -> bool:
    getter = getattr(secret, "get_secret_value", None)
    return bool(getter and str(getter()).strip())


def normalize_owner_name(name: str) -> str:
    """Normalize an assessor owner name for deterministic identity matching."""
    normalized = re.sub(r"[^A-Z0-9&]+", " ", name.upper())
    return re.sub(r"\s+", " ", normalized).strip()


def entity_type(name: str) -> str:
    """Classify common assessor owner-name suffixes."""
    normalized = normalize_owner_name(name)
    if re.search(r"\b(?:LLC|L L C|LIMITED LIABILITY COMPANY)\b", normalized):
        return "llc"
    if re.search(r"\b(?:TRUST|TRUSTEE|REVOCABLE|IRREVOCABLE)\b", normalized):
        return "trust"
    if re.search(
        r"\b(?:INC|INCORPORATED|CORP|CORPORATION|LTD|LP|LLP|COMPANY|CO|BANK|"
        r"ASSOCIATION|FOUNDATION|CHURCH)\b",
        normalized,
    ):
        return "corp"
    return "individual"


def _state_zip(address: str | None) -> tuple[str | None, str | None]:
    if not address:
        return None, None
    upper = address.upper()
    match = re.search(r"\b([A-Z]{2})\s+(\d{5})(?:-?\d{4})?\b", upper)
    if match:
        return match.group(1), match.group(2)
    state_match = re.search(
        r",\s*([A-Z]{2})(?=\s*(?:,?\s*\d{5}|$))",
        upper,
    )
    zip_match = re.search(r"\b(\d{5})(?:-?\d{4})?\b", upper)
    return (
        state_match.group(1) if state_match else None,
        zip_match.group(1) if zip_match else None,
    )


def is_absentee(parcel: ParcelRecord) -> bool | None:
    """Compare owner mailing state/ZIP with the site state/ZIP when available."""
    owner_state, owner_zip = _state_zip(parcel.owner_mailing_address)
    site_state, site_zip = _state_zip(parcel.site_address)
    if owner_state and site_state and owner_state != site_state:
        return True
    if owner_zip and site_zip:
        return owner_zip != site_zip
    return None


def owner_from_parcel(parcel: ParcelRecord) -> OwnerRecord:
    """Derive a normalized owner record from a parcel."""
    name = parcel.owner_name or "Unknown owner"
    return OwnerRecord(
        name=name,
        normalized_name=normalize_owner_name(name),
        entity_type=entity_type(name),
        absentee=is_absentee(parcel),
        mailing_address=parcel.owner_mailing_address,
        parcels=[parcel],
    )


class OwnerLookup:
    """Resolve geography, select a county provider, and cache owner results."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        cache: SQLiteCache | None = None,
        resolver: Callable[[str], Awaitable[GeoRef]] = resolve,
        provider_factory: Callable[
            [CountyParcelConfig], ParcelProvider
        ] = ArcgisParcelProvider,
        paid_provider_factories: tuple[PaidProviderFactory, ...] | None = None,
    ):
        self.config = resolve_runtime_config(config)
        self.cache = cache or SQLiteCache(self.config.cache_db_path)
        self.resolver = resolver
        self.provider_factory = provider_factory
        self._uses_default_provider_factory = provider_factory is ArcgisParcelProvider
        self._uses_default_paid_factories = paid_provider_factories is None
        self.paid_provider_factories = (
            _default_paid_provider_factories()
            if paid_provider_factories is None
            else paid_provider_factories
        )

    @staticmethod
    def _cache_key(
        address: str | None,
        apn: str | None,
        county_fips: str,
        provider_tag: str = "free",
    ) -> str:
        address_key = normalize_address(address or "")
        apn_key = re.sub(r"\s+", "", (apn or "").upper())
        # Bump the namespace when county coverage or mappings change so a
        # previously cached miss cannot hide a newly wired public assessor.
        return f"owner:v3:{provider_tag}:{county_fips}:{apn_key}:{address_key}"

    def _provider_tag(self) -> str:
        enabled = [
            name
            for name, secret in (
                ("regrid", self.config.regrid_api_key),
                ("attom", self.config.attom_api_key),
            )
            if _secret_is_set(secret)
        ]
        return "+".join(enabled) if enabled else "free"

    def _authorized_cache_ttl(
        self,
        county_config: CountyParcelConfig | None,
        provider_tag: str,
    ) -> tuple[int, bool]:
        """Gate every real source that could have contributed to an owner hit."""
        if not self._uses_default_provider_factory or not self._uses_default_paid_factories:
            # Explicit test/application providers own their cache contract.
            return _CACHE_TTL_SECONDS, False
        records = []
        sales_authorized = False
        if county_config is not None:
            records.append(
                require_url(
                    county_config.arcgis_url,
                    method="GET",
                    config=self.config,
                )
            )
            sales_authorized = county_sales_authorized(
                county_config,
                runtime_config=self.config,
            )
            if county_config.sales_layer and sales_authorized:
                records.append(
                    require_url(
                        county_config.sales_layer,
                        method="GET",
                        config=self.config,
                    )
                )
        for name in provider_tag.split("+"):
            url = _PAID_RIGHTS_URLS.get(name)
            if url is not None:
                records.append(require_url(url, method="GET", config=self.config))
        if not records:
            return 0, sales_authorized
        return (
            min(
                record.operating_policy.persistent_cache_ttl_seconds
                if record is not None
                else 0
                for record in records
            ),
            sales_authorized,
        )

    async def _paid_lookup(
        self,
        address: str | None,
        apn: str | None,
        geo: GeoRef,
    ) -> ParcelRecord | None:
        for factory in self.paid_provider_factories:
            provider = factory(self.config, self.cache)
            try:
                parcel = await provider.lookup(address, apn, geo)
            except ProviderUnavailable:
                continue
            except Exception as exc:
                logger.warning(
                    "Opt-in paid parcel provider %s failed non-fatally: %s",
                    type(provider).__name__,
                    safe_error_message(exc, config=self.config),
                )
                continue
            if parcel is not None:
                return parcel
        return None

    async def lookup(
        self,
        address: str | None = None,
        apn: str | None = None,
        geo: GeoRef | None = None,
        county: str | None = None,
    ) -> OwnerRecord | None:
        """Return owner and parcel data for an address or APN."""
        if not address and not apn:
            raise ValueError("address or apn is required")
        if geo is None:
            location = county or address
            if not location:
                raise ValueError("county is required when looking up an APN")
            geo = await self.resolver(location)
        county_config = config_for_geo(geo)
        county_fips = geo.county_fips or "unknown"
        provider_tag = self._provider_tag()
        cache_ttl, sales_authorized = self._authorized_cache_ttl(
            county_config,
            provider_tag,
        )
        cache_scope = f"{provider_tag}:sales" if sales_authorized else f"{provider_tag}:parcel"
        cache_key = self._cache_key(
            address,
            apn,
            county_fips,
            cache_scope,
        )
        if cache_ttl > 0:
            cached = await self.cache.get(cache_key)
            if cached == _MISSING:
                return None
            if cached is not None:
                return OwnerRecord.model_validate(cached)

        parcel = None
        if county_config is not None:
            provider = (
                ArcgisParcelProvider(
                    county_config,
                    runtime_config=self.config,
                )
                if self._uses_default_provider_factory
                else self.provider_factory(county_config)
            )
            try:
                parcel = await provider.lookup(address, apn, geo)
            except Exception as exc:
                if provider_tag == "free":
                    raise
                logger.warning(
                    "Free county parcel lookup failed for %s: %s",
                    safe_source_reference(county_config.name, config=self.config),
                    safe_error_message(exc, config=self.config),
                )
        if parcel is None or (provider_tag != "free" and not parcel.owner_name):
            paid_parcel = await self._paid_lookup(address, apn, geo)
            if paid_parcel is not None:
                parcel = paid_parcel
        if parcel is None:
            if cache_ttl > 0:
                await self.cache.set(
                    cache_key,
                    _MISSING,
                    ttl_seconds=min(_CACHE_TTL_SECONDS, cache_ttl),
                )
            return None
        owner = owner_from_parcel(parcel)
        if cache_ttl > 0:
            await self.cache.set(
                cache_key,
                owner.model_dump(mode="json"),
                ttl_seconds=min(_CACHE_TTL_SECONDS, cache_ttl),
            )
        return owner


__all__ = [
    "OwnerLookup",
    "entity_type",
    "is_absentee",
    "normalize_owner_name",
    "owner_from_parcel",
]
