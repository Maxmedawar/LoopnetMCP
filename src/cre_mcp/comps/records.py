"""County-limited public sale-comparable retrieval over shared ArcGIS HTTP."""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from cre_mcp.enrichment.counties import CountyParcelConfig, config_for_geo
from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models.comps import SaleComp
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.listings import Listing
from cre_mcp.scoring.rubrics import thresholds as T
from cre_mcp.sources.dedupe import normalize_address
from cre_mcp.source_rights.gate import require_source, require_url
from cre_mcp.source_rights.output import safe_source_reference

if TYPE_CHECKING:
    from cre_mcp.config import CreConfig

logger = logging.getLogger(__name__)


# Sales-only county coverage lives here so adding a public recorder layer does
# not accidentally claim that the same endpoint can supply parcel ownership.
COUNTY_SALES_ENDPOINTS: dict[str, CountyParcelConfig] = {
    "53033": CountyParcelConfig(
        fips="53033",
        name="King County",
        state="WA",
        arcgis_url=(
            "https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/"
            "PARCEL_SALES3YR_AREA_287/FeatureServer/0"
        ),
        field_map={},
        sales_layer=(
            "https://services.arcgis.com/Ej0PsM5Aw677QF1W/arcgis/rest/services/"
            "PARCEL_SALES3YR_AREA_287/FeatureServer/0"
        ),
        sales_field_map={
            "parcel_id": "PIN",
            "address": "address",
            "sale_price": "SalePrice",
            "time_adjusted_price": None,
            "sale_date": "SaleDate",
            "sqft": None,
            "units": None,
            "use_code": "Principal_Use",
            "lat": None,
            "lon": None,
        },
        sales_where="SalePrice > 10000 AND SaleDate IS NOT NULL",
    ),
    "37183": CountyParcelConfig(
        fips="37183",
        name="Wake County",
        state="NC",
        arcgis_url=(
            "https://maps.wakegov.com/arcgis/rest/services/Property/"
            "Parcels/MapServer/0"
        ),
        field_map={},
        sales_layer=(
            "https://maps.wakegov.com/arcgis/rest/services/Property/"
            "Parcels/MapServer/0"
        ),
        sales_field_map={
            "parcel_id": "PIN_NUM",
            "address": "SITE_ADDRESS",
            "sale_price": "TOTSALPRICE",
            "time_adjusted_price": None,
            "sale_date": "SALE_DATE",
            "sqft": "HEATEDAREA",
            "units": "UNITS",
            "use_code": "TYPE_USE_DECODE",
            "lat": None,
            "lon": None,
        },
        sales_where="TOTSALPRICE > 10000 AND SALE_DATE IS NOT NULL",
    ),
    "39049": CountyParcelConfig(
        fips="39049",
        name="Franklin County",
        state="OH",
        arcgis_url=(
            "https://gis.franklincountyohio.gov/hosting/rest/services/"
            "RealEstate/Sales_Information/FeatureServer/0"
        ),
        field_map={},
        sales_layer=(
            "https://gis.franklincountyohio.gov/hosting/rest/services/"
            "RealEstate/Sales_Information/FeatureServer/0"
        ),
        sales_field_map={
            "parcel_id": "PARCELID",
            "address": "SITEADDRESS",
            "sale_price": "SalePrice",
            "time_adjusted_price": None,
            "sale_date": "SALEDATE",
            "sqft": "RESFLRAREA",
            "units": None,
            "use_code": "CLASSDSCRP",
            "lat": None,
            "lon": None,
        },
        sales_where=(
            "SalePrice > 10000 AND SALEDATE IS NOT NULL AND ValidSale = 'Y'"
        ),
    ),
}


def sales_config_for_geo(geo: GeoRef | None) -> CountyParcelConfig | None:
    """Select a verified sales-only layer before the parcel registry fallback."""
    if geo is None or geo.county_fips is None:
        return None
    return COUNTY_SALES_ENDPOINTS.get(geo.county_fips) or config_for_geo(geo)


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


async def sale_comps(
    geo: GeoRef,
    subject: Listing,
    *,
    runtime_config: "CreConfig | None" = None,
) -> list[SaleComp]:
    """Return nearby, recent, like-use county sales when a verified layer exists."""
    config = sales_config_for_geo(geo)
    if config is None or not config.sales_layer:
        logger.info(
            "County sale comps unavailable for county_fips=%s; no verified layer is wired",
            geo.county_fips,
        )
        return []
    if subject.lat is None or subject.lon is None:
        logger.info(
            "County sale comps unavailable for %s; subject coordinates are missing",
            safe_source_reference(subject.address, config=runtime_config),
        )
        return []
    require_source(
        f"cre_mcp.comps.records:{config.fips}",
        config=runtime_config,
    )
    require_url(config.sales_layer, method="GET", config=runtime_config)
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


__all__ = [
    "COUNTY_SALES_ENDPOINTS",
    "map_sale_comp",
    "sale_comps",
    "sales_config_for_geo",
]
