"""County-limited public sale-comparable retrieval over shared ArcGIS HTTP."""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, date, datetime
from typing import Any

from cre_mcp.enrichment.counties import CountyParcelConfig, config_for_geo
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models.comps import SaleComp
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.listings import Listing
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.sources.dedupe import normalize_address

logger = logging.getLogger(__name__)


def _field(config: CountyParcelConfig, key: str) -> str | None:
    return config.sales_field_map.get(key)


def _value(
    attributes: dict[str, Any],
    config: CountyParcelConfig,
    key: str,
) -> Any:
    field = _field(config, key)
    return attributes.get(field) if field else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if abs(float(value)) > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m",
        "%Y%m%d",
        "%Y%m",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            parsed = datetime.strptime(text, fmt).date()
            if fmt in {"%Y-%m", "%Y%m"}:
                return f"{parsed.year:04d}-{parsed.month:02d}-01"
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def _geometry_point(attributes: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = attributes.get("_geometry")
    if not isinstance(geometry, dict):
        return None, None
    x = _number(geometry.get("x"))
    y = _number(geometry.get("y"))
    if x is not None and y is not None:
        return y, x
    rings = geometry.get("rings")
    points = [
        point
        for ring in rings if isinstance(ring, list)
        for point in ring if isinstance(point, list) and len(point) >= 2
    ] if isinstance(rings, list) else []
    xs = [_number(point[0]) for point in points]
    ys = [_number(point[1]) for point in points]
    valid_x = [value for value in xs if value is not None]
    valid_y = [value for value in ys if value is not None]
    if not valid_x or not valid_y:
        return None, None
    return sum(valid_y) / len(valid_y), sum(valid_x) / len(valid_x)


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3_958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_miles * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def map_sale_comp(
    attributes: dict[str, Any],
    config: CountyParcelConfig,
    *,
    subject: Listing | None = None,
) -> SaleComp | None:
    """Map one county sales feature through the registry field contract."""
    sale_price = _number(_value(attributes, config, "sale_price"))
    if sale_price is None or sale_price <= 0:
        return None
    lat = _number(_value(attributes, config, "lat"))
    lon = _number(_value(attributes, config, "lon"))
    if lat is None or lon is None:
        lat, lon = _geometry_point(attributes)
    distance = None
    if (
        subject
        and subject.lat is not None
        and subject.lon is not None
        and lat is not None
        and lon is not None
    ):
        distance = _distance_miles(subject.lat, subject.lon, lat, lon)
    return SaleComp(
        source=f"{config.name} public assessor/recorder sales",
        county_fips=config.fips,
        parcel_id=_text(_value(attributes, config, "parcel_id")),
        address=_text(_value(attributes, config, "address")),
        sale_price=sale_price,
        sale_date=_date(_value(attributes, config, "sale_date")),
        sqft=_number(_value(attributes, config, "sqft")),
        units=_number(_value(attributes, config, "units")),
        use_code=_text(_value(attributes, config, "use_code")),
        lat=lat,
        lon=lon,
        distance_miles=round(distance, 3) if distance is not None else None,
        time_adjusted_price=_number(_value(attributes, config, "time_adjusted_price")),
    )


def _use_category(value: str | None) -> str | None:
    text = (value or "").casefold()
    categories = {
        "multifamily": ("apartment", "multi", "condo"),
        "retail": ("retail", "store", "shop", "restaurant", "commercial"),
        "office": ("office",),
        "industrial": ("industrial", "warehouse", "manufactur"),
        "hospitality": ("hotel", "motel"),
        "residential": ("sfr", "townhome", "residential"),
        "land": ("vac", "land"),
    }
    return next(
        (
            category
            for category, words in categories.items()
            if any(word in text for word in words)
        ),
        None,
    )


def _like_subject(comp: SaleComp, subject: Listing) -> bool:
    subject_category = _use_category(
        " ".join(value for value in (subject.property_type, subject.property_subtype) if value)
    )
    comp_category = _use_category(comp.use_code)
    if subject_category and comp_category and subject_category != comp_category:
        return False
    if subject.size_sqft_num and comp.sqft:
        ratio = comp.sqft / subject.size_sqft_num
        if not T.SALE_COMP_MIN_SIZE_RATIO <= ratio <= T.SALE_COMP_MAX_SIZE_RATIO:
            return False
    return True


def _recent(comp: SaleComp) -> bool:
    if not comp.sale_date:
        return False
    try:
        sold = date.fromisoformat(comp.sale_date)
    except ValueError:
        return False
    age_years = max(0.0, (date.today() - sold).days / T.DAYS_PER_YEAR)
    return age_years <= T.SALE_COMP_MAX_AGE_YEARS


async def sale_comps(geo: GeoRef, subject: Listing) -> list[SaleComp]:
    """Return nearby, recent, like-use county sales when a verified layer exists."""
    config = config_for_geo(geo)
    if config is None or not config.sales_layer:
        logger.info(
            "County sale comps unavailable for county_fips=%s; no verified layer is wired",
            geo.county_fips,
        )
        return []
    if subject.lat is None or subject.lon is None:
        logger.info(
            "County sale comps unavailable for %s; subject coordinates are missing",
            subject.address,
        )
        return []
    fields = ",".join(
        dict.fromkeys(field for field in config.sales_field_map.values() if field)
    )
    date_field = _field(config, "sale_date")
    rows = await arcgis_query(
        config.sales_layer,
        where=config.sales_where,
        out_fields=fields or "*",
        geometry={
            "x": subject.lon,
            "y": subject.lat,
            "spatialReference": {"wkid": 4326},
        },
        return_geometry=True,
        out_sr=4326,
        distance=T.SALE_COMP_RADIUS_METERS,
        units="esriSRUnit_Meter",
        order_by_fields=f"{date_field} DESC" if date_field else None,
        result_count=T.SALE_COMP_QUERY_LIMIT,
    )
    subject_address = normalize_address(subject.address)
    mapped = [map_sale_comp(row, config, subject=subject) for row in rows]
    return [
        comp
        for comp in mapped
        if comp is not None
        and _recent(comp)
        and _like_subject(comp, subject)
        and (not comp.address or normalize_address(comp.address) != subject_address)
        and (
            comp.distance_miles is None
            or comp.distance_miles <= T.SALE_COMP_RADIUS_MILES
        )
    ]


__all__ = ["map_sale_comp", "sale_comps"]
