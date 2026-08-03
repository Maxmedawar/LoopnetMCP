"""ArcGIS-backed public assessor parcel provider."""

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from cre_mcp.enrichment.counties import CountyParcelConfig
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.sources.dedupe import normalize_address
from cre_mcp.source_rights.gate import SourceRightsDeniedError, require_source
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference

if TYPE_CHECKING:
    from cre_mcp.config import CreConfig

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
    text = _text(value)
    if text is None:
        return None
    for fmt in ("%Y%m%d", "%Y%m", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if fmt == "%Y%m":
            return f"{parsed.year:04d}-{parsed.month:02d}-01"
        return parsed.isoformat()
    return text


def _join_address(*parts: Any) -> str | None:
    values = [_text(part) for part in parts]
    return ", ".join(value for value in values if value) or None


def _compose_address(
    street: Any,
    city: Any,
    state: Any,
    zip_code: Any,
) -> str | None:
    """Append locality pieces only when a county's combined field omits them."""
    first = _text(street)
    if first is None:
        return _join_address(city, state, zip_code)
    parts = [first]
    existing = first.upper()
    city_text = _text(city)
    state_text = _text(state)
    zip_text = _text(zip_code)
    if city_text and city_text.upper() not in existing:
        parts.append(city_text)
    if state_text and not re.search(
        rf"\b{re.escape(state_text.upper())}\b",
        existing,
    ):
        parts.append(state_text)
    if zip_text and not re.search(rf"\b{re.escape(zip_text)}\b", existing):
        parts.append(zip_text)
    return ", ".join(parts)


def _join_text(*parts: Any) -> str | None:
    values = [_text(part) for part in parts]
    return " ".join(value for value in values if value) or None


def _street_prefix(address: str) -> tuple[str | None, str | None]:
    """Return house number and suffix-free street prefix for county queries."""
    normalized = normalize_address(address.split(",", 1)[0])
    parts = normalized.split()
    if len(parts) < 2:
        return None, None
    number = parts[0]
    street = parts[1:]
    if street[-1] in {
        "AVE",
        "BLVD",
        "CIR",
        "CT",
        "DR",
        "HWY",
        "LN",
        "PKWY",
        "PL",
        "PLZ",
        "RD",
        "ST",
        "TRL",
        "WAY",
    }:
        street = street[:-1]
    return number, " ".join(street) or None


def map_parcel(
    attributes: dict[str, Any],
    config: CountyParcelConfig,
) -> ParcelRecord:
    """Map one county feature through its declared field schema."""
    site_state = _value(attributes, config, "site_state") or config.state
    site_street = _text(_value(attributes, config, "site_addr")) or _join_text(
        _value(attributes, config, "site_number"),
        _value(attributes, config, "site_pre_dir"),
        _value(attributes, config, "site_street"),
        _value(attributes, config, "site_suffix"),
        _value(attributes, config, "site_post_dir"),
        _value(attributes, config, "site_unit"),
    )
    site_address = _compose_address(
        site_street,
        _value(attributes, config, "site_city"),
        site_state,
        _value(attributes, config, "site_zip"),
    )
    owner_mailing_address = _compose_address(
        _value(attributes, config, "owner_mailing_addr"),
        _value(attributes, config, "owner_mailing_city"),
        _value(attributes, config, "owner_mailing_state"),
        _value(attributes, config, "owner_mailing_zip"),
    )
    return ParcelRecord(
        apn=_text(_value(attributes, config, "apn")),
        site_address=site_address,
        owner_name=_text(_value(attributes, config, "owner_name")) or _join_text(
            _value(attributes, config, "owner_name_1"),
            _value(attributes, config, "owner_name_2"),
        ),
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

    def __init__(
        self,
        config: CountyParcelConfig,
        *,
        runtime_config: "CreConfig | None" = None,
    ):
        self.config = config
        self.runtime_config = runtime_config
        self.sales_authorized = county_sales_authorized(
            config,
            runtime_config=runtime_config,
        )

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
            number, street_prefix = _street_prefix(normalized)
            query_prefix = " ".join(
                value for value in (number, street_prefix) if value
            )
            where = f"UPPER({address_field}) LIKE '%{_quote(query_prefix)}%'"
        elif (
            address
            and self.config.address_number_field
            and self.config.address_street_field
        ):
            number, street_prefix = _street_prefix(address)
            if not number or not street_prefix:
                return None
            where = (
                f"{self.config.address_number_field}='{_quote(number)}' AND "
                f"UPPER({self.config.address_street_field}) LIKE "
                f"'{_quote(street_prefix)}%'"
            )
        else:
            return None

        restricted_sale_fields = {
            field.casefold()
            for field in (
                self.config.field_map.get("last_sale_price"),
                self.config.field_map.get("last_sale_date"),
                self.config.sales_field_map.get("sale_price"),
                self.config.sales_field_map.get("time_adjusted_price"),
                self.config.sales_field_map.get("sale_date"),
            )
            if field
        }
        fields = ",".join(
            dict.fromkeys(
                field
                for key, field in self.config.field_map.items()
                if field
                and (
                    self.sales_authorized
                    or key not in {"last_sale_price", "last_sale_date"}
                )
            )
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
        if not self.sales_authorized:
            parcel = parcel.model_copy(
                update={
                    "last_sale_price": None,
                    "last_sale_date": None,
                    "raw": {
                        key: value
                        for key, value in parcel.raw.items()
                        if key.casefold() not in restricted_sale_fields
                    },
                }
            )
        return await self._with_latest_sale(parcel)

    async def _with_latest_sale(self, parcel: ParcelRecord) -> ParcelRecord:
        """Attach the subject's own latest verified sale when the county exposes it."""
        if not self.sales_authorized:
            return parcel
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
                safe_source_reference(parcel.apn or "", config=self.runtime_config),
                safe_source_reference(self.config.name, config=self.runtime_config),
                safe_error_message(exc, config=self.runtime_config),
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


def county_sales_authorized(
    county: CountyParcelConfig,
    *,
    runtime_config: "CreConfig | None" = None,
) -> bool:
    """Return whether this request may exercise the county sales capability."""
    if not county.sales_layer:
        return False
    try:
        require_source(
            f"cre_mcp.comps.records:{county.fips}",
            config=runtime_config,
        )
    except SourceRightsDeniedError:
        return False
    return True


__all__ = ["ArcgisParcelProvider", "county_sales_authorized", "map_parcel"]
