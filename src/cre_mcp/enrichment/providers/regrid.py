"""Opt-in Regrid nationwide parcel and owner provider.

Regrid bills by returned parcel records. Calls are therefore key-gated, limited
to one result, and persistently cached; no key means no request and no charge.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.base import ProviderUnavailable
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models.comps import CompsProviderResult, ValueEstimate
from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.listings import Listing

_BASE_URL = "https://app.regrid.com/api/v2/parcels"
_PARCEL_CACHE_TTL = 365 * 24 * 60 * 60
_REGRID_VALUE_CONFIDENCE = 0.30
_REGRID_VALUE_ERROR_BAND = 0.30


def _text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number > 0 else None


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        return {}
    fields = properties.get("fields")
    if isinstance(fields, dict):
        return {**properties, **fields}
    return properties


def _features(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    parcels = payload.get("parcels")
    rows = parcels.get("features") if isinstance(parcels, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _mailing(properties: dict[str, Any]) -> str | None:
    street = _text(properties.get("mailadd") or properties.get("mail_address"))
    city = _text(properties.get("mail_city") or properties.get("mailcity"))
    state = _text(properties.get("mail_state2") or properties.get("mailstate"))
    zip_code = _text(properties.get("mail_zip") or properties.get("mailzip"))
    locality = " ".join(value for value in (city, state, zip_code) if value)
    return ", ".join(value for value in (street, locality) if value) or None


def _site_address(properties: dict[str, Any]) -> str | None:
    street = _text(properties.get("address") or properties.get("headline"))
    city = _text(properties.get("scity"))
    state = _text(properties.get("state2"))
    zip_code = _text(properties.get("szip"))
    locality = " ".join(value for value in (city, state, zip_code) if value)
    return ", ".join(value for value in (street, locality) if value) or None


def map_regrid_parcel(feature: dict[str, Any]) -> ParcelRecord:
    """Map one documented Regrid GeoJSON feature into the parcel contract."""
    properties = _properties(feature)
    return ParcelRecord(
        apn=_text(properties.get("parcelnumb") or properties.get("tax_id")),
        site_address=_site_address(properties),
        owner_name=_text(
            properties.get("owner")
            or properties.get("enhanced_owner_name")
            or properties.get("owner_name")
        ),
        owner_mailing_address=_mailing(properties),
        assessed_value=_number(properties.get("parval")),
        building_sqft=_number(
            properties.get("ll_bldg_footprint_sqft")
            or properties.get("building_sqft")
            or properties.get("bldg_sqft")
        ),
        units=_number(properties.get("numunits")),
        land_value=_number(properties.get("landval")),
        last_sale_price=_number(properties.get("saleprice")),
        last_sale_date=_text(properties.get("saledate")),
        year_built=_integer(properties.get("yearbuilt")),
        use_code=_text(properties.get("usedesc") or properties.get("usecode")),
        lat=_number(properties.get("lat")),
        lon=_number(properties.get("lon")),
        raw={"provider": "regrid", "feature": feature},
    )


class RegridProvider:
    """Regrid implementation of parcel and weak value-anchor contracts."""

    name = "regrid"

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        fetch: FetchClient | None = None,
        cache: SQLiteCache | None = None,
    ):
        self.config = config or CreConfig()
        self.fetch = fetch or get_fetch_client()
        self.cache = cache or SQLiteCache(self.config.cache_db_path)

    def _api_key(self) -> str:
        if self.config.regrid_api_key is None:
            raise ProviderUnavailable(
                "CRE_REGRID_API_KEY is not configured; Regrid paid calls are off"
            )
        value = self.config.regrid_api_key.get_secret_value().strip()
        if not value:
            raise ProviderUnavailable(
                "CRE_REGRID_API_KEY is not configured; Regrid paid calls are off"
            )
        return value

    @staticmethod
    def _cache_key(*parts: Any) -> str:
        material = "|".join(str(part or "").strip().casefold() for part in parts)
        digest = hashlib.sha256(material.encode()).hexdigest()
        return f"paid:regrid:v1:parcel:{digest}"

    async def lookup(
        self,
        address: str | None,
        apn: str | None,
        geo: GeoRef | None,
    ) -> ParcelRecord | None:
        """Return one paid Regrid record only after explicit key opt-in."""
        token = self._api_key()
        if not address and not apn:
            return None
        cache_key = self._cache_key(address, apn, geo.county_fips if geo else None)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return None if cached.get("missing") else ParcelRecord.model_validate(cached)

        if apn:
            endpoint = "apn"
            params: dict[str, Any] = {"parcelnumb": apn}
        else:
            endpoint = "address"
            params = {"query": address}
        params.update(
            {
                "limit": 1,
                "return_geometry": "false",
                "return_custom": "false",
                "token": token,
            }
        )
        payload = await self.fetch.get_json(
            f"{_BASE_URL}/{endpoint}?{urlencode(params)}"
        )
        rows = _features(payload)
        parcel = map_regrid_parcel(rows[0]) if rows else None
        await self.cache.set(
            cache_key,
            parcel.model_dump(mode="json") if parcel else {"missing": True},
            ttl_seconds=_PARCEL_CACHE_TTL,
        )
        return parcel

    async def get_comps(
        self,
        subject: Listing,
        geo: GeoRef | None,
    ) -> CompsProviderResult:
        """Return an explicitly weak Regrid assessor anchor, never an AVM claim."""
        parcel = await self.lookup(subject.address, None, geo)
        estimate = None
        if parcel and parcel.assessed_value and parcel.assessed_value > 0:
            mid = parcel.assessed_value
            error = _REGRID_VALUE_ERROR_BAND
            estimate = ValueEstimate(
                value=mid,
                low=mid * (1 - error),
                mid=mid,
                high=mid * (1 + error),
                method="regrid",
                n_comps=0,
                confidence=_REGRID_VALUE_CONFIDENCE,
                error_band=error,
                as_of=date.today().isoformat(),
                source=(
                    "Regrid paid nationwide assessor value (opt-in, pay-per-use); "
                    "not closed-sale comps or a property-level AVM."
                ),
            )
        return CompsProviderResult(
            provider=self.name,
            comps=[],
            value_estimate=estimate,
        )


__all__ = ["RegridProvider", "map_regrid_parcel"]
