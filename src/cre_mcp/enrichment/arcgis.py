"""ArcGIS-backed public assessor parcel provider."""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from cre_mcp.enrichment.counties import CountyParcelConfig
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.sources.dedupe import normalize_address

logger = logging.getLogger(__name__)


def _field(config: CountyParcelConfig, key: str) -> str | None:
    return config.field_map.get(key)


def _value(
    attributes: dict[str, Any],
    config: CountyParcelConfig,
    key: str,
) -> Any:
    field = _field(config, key)
    return attributes.get(field) if field else None


def _text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _year(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number > 0 else None


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = (
            float(value) / 1000
            if abs(float(value)) > 10_000_000_000
            else float(value)
        )
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return _text(value)


def _join_address(*parts: Any) -> str | None:
    values = [_text(part) for part in parts]
    return ", ".join(value for value in values if value) or None


def map_parcel(
    attributes: dict[str, Any],
    config: CountyParcelConfig,
) -> ParcelRecord:
    """Map one county feature through its declared field schema."""
    site_state = _value(attributes, config, "site_state") or config.state
    site_address = _join_address(
        _value(attributes, config, "site_addr"),
        _value(attributes, config, "site_city"),
        site_state,
        _value(attributes, config, "site_zip"),
    )
    owner_mailing_address = _join_address(
        _value(attributes, config, "owner_mailing_addr"),
        _value(attributes, config, "owner_mailing_city"),
        _value(attributes, config, "owner_mailing_state"),
        _value(attributes, config, "owner_mailing_zip"),
    )
    return ParcelRecord(
        apn=_text(_value(attributes, config, "apn")),
        site_address=site_address,
        owner_name=_text(_value(attributes, config, "owner_name")),
        owner_mailing_address=owner_mailing_address,
        assessed_value=_number(_value(attributes, config, "assessed_value")),
        building_sqft=_number(_value(attributes, config, "building_sqft")),
        units=_number(_value(attributes, config, "units")),
        land_value=_number(_value(attributes, config, "land_value")),
        last_sale_price=_number(_value(attributes, config, "last_sale_price")),
        last_sale_date=_date(_value(attributes, config, "last_sale_date")),
        year_built=_year(_value(attributes, config, "year_built")),
        use_code=_text(_value(attributes, config, "use_code")),
        lat=_number(_value(attributes, config, "lat")),
        lon=_number(_value(attributes, config, "lon")),
        raw=dict(attributes),
    )


def _quote(value: str) -> str:
    return value.replace("'", "''")


class ArcgisParcelProvider:
    """Query one configured county assessor ArcGIS layer."""

    def __init__(self, config: CountyParcelConfig):
        self.config = config

    async def lookup(
        self,
        address: str | None,
        apn: str | None,
        geo: GeoRef | None,
    ) -> ParcelRecord | None:
        apn_field = _field(self.config, "apn")
        address_field = _field(self.config, "site_addr")
        if apn and apn_field:
            normalized_apn = re.sub(r"\s+", "", apn).upper()
            where = f"UPPER({apn_field})='{_quote(normalized_apn)}'"
        elif address and address_field:
            street = address.split(",", 1)[0]
            normalized = normalize_address(street)
            if not normalized:
                return None
            where = f"UPPER({address_field})='{_quote(normalized)}'"
        else:
            return None

        fields = ",".join(
            dict.fromkeys(field for field in self.config.field_map.values() if field)
        )
        features = await arcgis_query(
            self.config.arcgis_url,
            where=where,
            out_fields=fields or "*",
            result_count=1,
        )
        if not features:
            return None
        parcel = map_parcel(features[0], self.config)
        return await self._with_latest_sale(parcel)

    async def _with_latest_sale(self, parcel: ParcelRecord) -> ParcelRecord:
        """Attach the subject's own latest verified sale when the county exposes it."""
        parcel_field = self.config.sales_field_map.get("parcel_id")
        price_field = self.config.sales_field_map.get("sale_price")
        date_field = self.config.sales_field_map.get("sale_date")
        if (
            not self.config.sales_layer
            or not parcel.apn
            or not parcel_field
            or not price_field
        ):
            return parcel
        where = (
            f"({self.config.sales_where}) AND "
            f"UPPER({parcel_field})='{_quote(parcel.apn.upper())}'"
        )
        fields = ",".join(
            field for field in (price_field, date_field) if field is not None
        )
        try:
            rows = await arcgis_query(
                self.config.sales_layer,
                where=where,
                out_fields=fields,
                order_by_fields=f"{date_field} DESC" if date_field else None,
                result_count=1,
            )
        except Exception as exc:
            logger.warning(
                "Latest parcel sale unavailable for %s in %s: %s",
                parcel.apn,
                self.config.name,
                exc,
            )
            return parcel
        if not rows:
            return parcel
        price = _number(rows[0].get(price_field))
        sold = _date(rows[0].get(date_field)) if date_field else None
        if price is None:
            return parcel
        return parcel.model_copy(
            update={"last_sale_price": price, "last_sale_date": sold}
        )


__all__ = ["ArcgisParcelProvider", "map_parcel"]
