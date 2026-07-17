"""Opt-in ATTOM parcel, sale-comparable, and AVM provider.

ATTOM is pay-per-use. This module never makes a request unless
``CRE_ATTOM_API_KEY`` is explicitly configured, and normalized responses are
persisted before another paid call is considered.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.base import ProviderUnavailable
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models.comps import CompsProviderResult, SaleComp, ValueEstimate
from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.listings import Listing

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
_PARCEL_CACHE_TTL = 365 * 24 * 60 * 60
_COMPS_CACHE_TTL = 30 * 24 * 60 * 60
_DEFAULT_AVM_CONFIDENCE = 0.55


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


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _dig(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _first(data: dict[str, Any], *paths: str) -> Any:
    return next(
        (value for path in paths if (value := _dig(data, path)) not in (None, "")),
        None,
    )


def _records(payload: Any, keys: tuple[str, ...] = ("property",)) -> list[dict[str, Any]]:
    """Find a documented ATTOM record list while tolerating envelope drift."""
    if not isinstance(payload, dict):
        return []
    wanted = {key.casefold() for key in keys}
    queue: list[Any] = [payload]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            for key, value in current.items():
                if key.casefold() in wanted and isinstance(value, list):
                    rows = [row for row in value if isinstance(row, dict)]
                    if rows:
                        return rows
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(current, list):
            queue.extend(current)
    return []


def _address(record: dict[str, Any]) -> str | None:
    one_line = _text(_first(record, "address.oneLine", "address.oneLineAddress"))
    if one_line:
        return one_line
    line1 = _text(_first(record, "address.line1", "address.street"))
    locality = _text(_first(record, "address.locality", "address.city"))
    state = _text(_first(record, "address.countrySubd", "address.state"))
    postal = _text(_first(record, "address.postal1", "address.zip"))
    second = " ".join(value for value in (locality, state, postal) if value)
    return ", ".join(value for value in (line1, second) if value) or None


def map_attom_parcel(record: dict[str, Any]) -> ParcelRecord:
    """Map one ATTOM detail-owner record into the shared parcel contract."""
    owner_name = _text(
        _first(
            record,
            "owner.owner1.fullName",
            "owner.owner1.fullname",
            "owner.owner1.name",
            "owner.ownerName",
        )
    )
    owner_two = _text(
        _first(record, "owner.owner2.fullName", "owner.owner2.fullname")
    )
    if owner_name and owner_two:
        owner_name = f"{owner_name} & {owner_two}"
    mailing = _text(
        _first(
            record,
            "owner.mailingAddressOneLine",
            "owner.mailAddress.oneLine",
            "owner.mailAddress",
        )
    )
    return ParcelRecord(
        apn=_text(_first(record, "identifier.apn", "identifier.apnOrig")),
        site_address=_address(record),
        owner_name=owner_name,
        owner_mailing_address=mailing,
        assessed_value=_number(
            _first(
                record,
                "assessment.market.mktTtlValue",
                "assessment.assessed.assdTtlValue",
            )
        ),
        building_sqft=_number(
            _first(
                record,
                "building.size.bldgSize",
                "building.size.livingSize",
                "building.size.universalSize",
            )
        ),
        units=_number(
            _first(record, "building.rooms.unitsCount", "summary.unitsCount")
        ),
        land_value=_number(_first(record, "assessment.market.mktLandValue")),
        last_sale_price=_number(
            _first(record, "sale.amount.saleAmt", "sale.saleAmount")
        ),
        last_sale_date=_date(
            _first(record, "sale.saleTransDate", "sale.saleSearchDate")
        ),
        year_built=_integer(
            _first(record, "summary.yearBuilt", "building.summary.yearBuilt")
        ),
        use_code=_text(
            _first(record, "summary.propType", "summary.propSubType", "lot.siteZoningIdent")
        ),
        lat=_number(_first(record, "location.latitude", "location.lat")),
        lon=_number(_first(record, "location.longitude", "location.lon")),
        raw={"provider": "attom", "record": record},
    )


def map_attom_comp(record: dict[str, Any], county_fips: str = "") -> SaleComp | None:
    """Map one ATTOM comparable property into a labeled sale record."""
    price = _number(
        _first(
            record,
            "sale.amount.saleAmt",
            "sale.saleAmount",
            "salesHistory.propertySalesAmount",
            "propertySalesAmount",
        )
    )
    if price is None or price <= 0:
        return None
    fips = _text(_first(record, "identifier.fips", "location.fips")) or county_fips
    return SaleComp(
        source="ATTOM paid sales comparables (opt-in)",
        county_fips=fips,
        parcel_id=_text(_first(record, "identifier.apn", "identifier.attomId")),
        address=_address(record),
        sale_price=price,
        sale_date=_date(
            _first(
                record,
                "sale.saleTransDate",
                "sale.saleSearchDate",
                "salesHistory.propertySalesDate",
                "propertySalesDate",
            )
        ),
        sqft=_number(
            _first(
                record,
                "building.size.bldgSize",
                "building.size.livingSize",
                "building.size.universalSize",
            )
        ),
        units=_number(
            _first(record, "building.rooms.unitsCount", "summary.unitsCount")
        ),
        use_code=_text(
            _first(record, "summary.propType", "summary.propSubType")
        ),
        lat=_number(_first(record, "location.latitude", "location.lat")),
        lon=_number(_first(record, "location.longitude", "location.lon")),
        distance_miles=_number(_first(record, "distance", "location.distance")),
    )


def map_attom_avm(payload: Any) -> ValueEstimate | None:
    """Map ATTOM's property-level AVM with its native range and confidence."""
    rows = _records(payload)
    if not rows:
        return None
    record = rows[0]
    mid = _number(_first(record, "avm.amount.value", "avm.amount.valueAmount"))
    if mid is None or mid <= 0:
        return None
    low = _number(_first(record, "avm.amount.valueLow", "avm.amount.low"))
    high = _number(_first(record, "avm.amount.valueHigh", "avm.amount.high"))
    score = _number(_first(record, "avm.amount.scr", "avm.scr"))
    confidence = _DEFAULT_AVM_CONFIDENCE if score is None else score
    if confidence > 1:
        confidence /= 100
    confidence = max(0.0, min(confidence, 1.0))
    error_band = None
    if low is not None and high is not None and mid > 0:
        error_band = max(0.0, (high - low) / (2 * mid))
    return ValueEstimate(
        value=mid,
        low=low,
        mid=mid,
        high=high,
        method="attom",
        n_comps=0,
        confidence=round(confidence, 4),
        error_band=round(error_band, 4) if error_band is not None else None,
        as_of=_date(_first(record, "avm.eventDate", "avm.amount.eventDate"))
        or date.today().isoformat(),
        source=(
            "ATTOM paid property-level AVM (opt-in, pay-per-use); verify with an "
            "appraiser and local closed-sale evidence."
        ),
    )


class AttomProvider:
    """ATTOM implementation of both parcel and comps provider contracts."""

    name = "attom"

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
        if self.config.attom_api_key is None:
            raise ProviderUnavailable(
                "CRE_ATTOM_API_KEY is not configured; ATTOM paid calls are off"
            )
        value = self.config.attom_api_key.get_secret_value().strip()
        if not value:
            raise ProviderUnavailable(
                "CRE_ATTOM_API_KEY is not configured; ATTOM paid calls are off"
            )
        return value

    @staticmethod
    def _cache_key(kind: str, *parts: Any) -> str:
        material = "|".join(str(part or "").strip().casefold() for part in parts)
        digest = hashlib.sha256(material.encode()).hexdigest()
        return f"paid:attom:v1:{kind}:{digest}"

    @staticmethod
    def _address_parts(address: str) -> tuple[str, str]:
        first, separator, remainder = address.partition(",")
        return first.strip(), remainder.strip() if separator else ""

    @staticmethod
    def _subject_parts(subject: Listing) -> tuple[str, str]:
        line1, line2 = AttomProvider._address_parts(subject.address)
        if not line2:
            line2 = " ".join(
                value
                for value in (subject.city, subject.state, subject.zip_code)
                if value
            )
        return line1, line2

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{_BASE_URL}/{path.lstrip('/')}?{urlencode(params)}"
        return await self.fetch.get_json(
            url,
            headers={"Accept": "application/json", "apikey": self._api_key()},
        )

    async def lookup(
        self,
        address: str | None,
        apn: str | None,
        geo: GeoRef | None,
    ) -> ParcelRecord | None:
        """Return ATTOM detail-owner data only after explicit key opt-in."""
        self._api_key()
        if not address and not apn:
            return None
        cache_key = self._cache_key("parcel", address, apn, geo.county_fips if geo else None)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return None if cached.get("missing") else ParcelRecord.model_validate(cached)

        params: dict[str, Any]
        if address:
            address1, address2 = self._address_parts(address)
            params = {"address1": address1, "address2": address2}
        else:
            params = {"apn": apn}
            if geo and geo.county_fips:
                params["fips"] = geo.county_fips
        payload = await self._get("property/detailowner", params)
        rows = _records(payload)
        parcel = map_attom_parcel(rows[0]) if rows else None
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
        """Return ATTOM sale comps plus AVM, cached before another paid call."""
        self._api_key()
        cache_key = self._cache_key(
            "comps", subject.address, subject.source_id, geo.county_fips if geo else None
        )
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return CompsProviderResult.model_validate(cached)

        address1, address2 = self._subject_parts(subject)
        params = {"address1": address1, "address2": address2, "radius": 5, "pageSize": 25}
        comps: list[SaleComp] = []
        avm: ValueEstimate | None = None
        successful_response = False
        try:
            payload = await self._get("salescomparables", params)
            successful_response = True
            rows = _records(
                payload,
                keys=("comparables", "comparableProperties", "property"),
            )
            county_fips = geo.county_fips if geo and geo.county_fips else ""
            comps = [
                comp
                for row in rows
                if (comp := map_attom_comp(row, county_fips)) is not None
            ]
        except Exception as exc:
            logger.warning("ATTOM paid sales comparables unavailable: %s", exc)
        try:
            payload = await self._get(
                "attomavm/detail",
                {"address1": address1, "address2": address2},
            )
            successful_response = True
            avm = map_attom_avm(payload)
        except Exception as exc:
            logger.warning("ATTOM paid AVM unavailable: %s", exc)

        result = CompsProviderResult(
            provider=self.name,
            comps=comps,
            value_estimate=avm,
        )
        if successful_response:
            await self.cache.set(
                cache_key,
                result.model_dump(mode="json"),
                ttl_seconds=_COMPS_CACHE_TTL,
            )
        return result


__all__ = [
    "AttomProvider",
    "map_attom_avm",
    "map_attom_comp",
    "map_attom_parcel",
]
