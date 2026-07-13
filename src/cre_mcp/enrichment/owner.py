"""Cached county parcel lookup and owner derivation."""

import re
from collections.abc import Awaitable, Callable

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.arcgis import ArcgisParcelProvider
from cre_mcp.enrichment.base import ParcelProvider
from cre_mcp.enrichment.counties import CountyParcelConfig, config_for_geo
from cre_mcp.geo.resolver import resolve
from cre_mcp.models.enrichment import OwnerRecord, ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.sources.dedupe import normalize_address

_CACHE_TTL_SECONDS = 90 * 24 * 60 * 60
_MISSING = {"missing": True}


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
    ):
        self.config = config or CreConfig()
        self.cache = cache or SQLiteCache(self.config.cache_db_path)
        self.resolver = resolver
        self.provider_factory = provider_factory

    @staticmethod
    def _cache_key(
        address: str | None,
        apn: str | None,
        county_fips: str,
    ) -> str:
        address_key = normalize_address(address or "")
        apn_key = re.sub(r"\s+", "", (apn or "").upper())
        return f"owner:v1:{county_fips}:{apn_key}:{address_key}"

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
        if county_config is None:
            return None

        cache_key = self._cache_key(address, apn, county_config.fips)
        cached = await self.cache.get(cache_key)
        if cached == _MISSING:
            return None
        if cached is not None:
            return OwnerRecord.model_validate(cached)

        provider = self.provider_factory(county_config)
        parcel = await provider.lookup(address, apn, geo)
        if parcel is None:
            await self.cache.set(cache_key, _MISSING, ttl_seconds=_CACHE_TTL_SECONDS)
            return None
        owner = owner_from_parcel(parcel)
        await self.cache.set(
            cache_key,
            owner.model_dump(mode="json"),
            ttl_seconds=_CACHE_TTL_SECONDS,
        )
        return owner


__all__ = [
    "OwnerLookup",
    "entity_type",
    "is_absentee",
    "normalize_owner_name",
    "owner_from_parcel",
]
