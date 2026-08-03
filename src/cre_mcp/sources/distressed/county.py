"""Configuration-driven county foreclosure and tax-sale source."""

import logging
import re
from dataclasses import dataclass
from typing import Any

from cre_mcp.http.arcgis import arcgis_query
from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.models.geo import GeoRef
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CountyConfig:
    """ArcGIS layer and field mapping for one public county feed."""

    fips: str
    name: str
    state: str
    arcgis_url: str
    field_map: dict[str, str]
    distress_type: str


COUNTY_ENDPOINTS: dict[str, CountyConfig] = {
    "37081": CountyConfig(
        fips="37081",
        name="Guilford County",
        state="NC",
        arcgis_url=(
            "https://gcgis.guilfordcountync.gov/arcgis/rest/services/"
            "Foreclosure/ForeclosuresPublic/FeatureServer/0"
        ),
        field_map={
            "id": "OBJECTID",
            "parcel_id": "PARCEL_ID",
            "name": "Owner",
            "address": "LOCATION_ADDR",
            "property_type": "Property_Type",
            "assessed_value": "Total_Assessed",
            "year_built": "YEAR_BUILT",
            "size_sqft": "Structure_Size",
            "lot_size": "Lot_Size",
            "auction_date": "AuctionDate",
            "lat": "Centroid_Y",
            "lon": "Centroid_X",
        },
        distress_type="foreclosure",
    ),
    "04025": CountyConfig(
        fips="04025",
        name="Yavapai County",
        state="AZ",
        arcgis_url=(
            "https://services1.arcgis.com/BajuNXbtZNiBKFkx/arcgis/rest/"
            "services/Tax_Sale_map_Manual_Load_for_Tax_Sale/FeatureServer/0"
        ),
        field_map={
            "id": "OBJECTID",
            "parcel_id": "TrsParcelNo",
            "name": "NAME",
            "address": "SITUS_ADD_DOR",
            "price": "Amount",
            "lot_size": "ACRE_CALC",
            "tax_year": "TaxYear",
        },
        distress_type="tax_sale",
    ),
    "08035": CountyConfig(
        fips="08035",
        name="Douglas County",
        state="CO",
        arcgis_url=(
            "https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/"
            "services/Tax_Sale_List_Locations/FeatureServer/0"
        ),
        field_map={
            "id": "OBJECTID",
            "parcel_id": "State_Parcel_No",
            "name": "Owner_Name",
            "address": "Address1",
            "city": "City",
            "state": "State",
            "zip": "ZipCode",
            "price": "Total_Due",
            "tax_year": "Tax_Year",
            "description": "Property_Description",
        },
        distress_type="tax_sale",
    ),
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    match = re.search(r"-?[\d,.]+", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _value(attributes: dict[str, Any], config: CountyConfig, key: str) -> Any:
    field = config.field_map.get(key)
    return attributes.get(field) if field else None


def _property_type(value: Any) -> str:
    text = str(value or "").casefold()
    if "multi" in text or "apartment" in text:
        return "multifamily"
    if "retail" in text or "commercial" in text:
        return "retail"
    if "industrial" in text:
        return "industrial"
    if "land" in text or "vacant" in text:
        return "land"
    return "special-purpose"


def map_county_listing(
    attributes: dict[str, Any],
    config: CountyConfig,
) -> Listing:
    """Map fields according to a county's declared schema."""
    object_id = str(
        _value(attributes, config, "id")
        or _value(attributes, config, "parcel_id")
        or ""
    )
    source_id = f"{config.fips}:{object_id}"
    address = str(_value(attributes, config, "address") or "").strip().title()
    city = str(_value(attributes, config, "city") or "").strip().title()
    state = str(_value(attributes, config, "state") or config.state).strip().upper()
    zip_value = _value(attributes, config, "zip")
    zip_code = str(zip_value).strip()[:5] if zip_value not in (None, "") else None
    price = _number(_value(attributes, config, "price"))
    assessed = _number(_value(attributes, config, "assessed_value"))
    size = _number(_value(attributes, config, "size_sqft"))
    year = _number(_value(attributes, config, "year_built"))
    lot = _number(_value(attributes, config, "lot_size"))
    url = f"{config.arcgis_url}?record={object_id}"
    raw = dict(attributes)
    raw.update(
        {
            "assessed_value": assessed,
            "avm": assessed,
            "tax_sale_amount": price,
            "distress_type": config.distress_type,
            "county_fips": config.fips,
        }
    )
    owner = str(_value(attributes, config, "name") or "").strip()
    return Listing(
        source="county",
        source_id=source_id,
        refs=[ListingRef(source="county", source_id=source_id, url=url)],
        name=address or owner or f"{config.name} distressed parcel {object_id}",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        property_type=_property_type(_value(attributes, config, "property_type")),
        property_subtype=str(_value(attributes, config, "property_type") or "") or None,
        listing_type="for-sale",
        price=f"${price:,.0f}" if price is not None else None,
        size_sqft=f"{size:,.0f} SF" if size is not None else None,
        lot_size=f"{lot:g} acres" if lot is not None else None,
        year_built=str(int(year)) if year is not None else None,
        description=str(_value(attributes, config, "description") or "") or None,
        url=url,
        last_updated=str(_value(attributes, config, "auction_date") or "") or None,
        price_usd=price,
        size_sqft_num=size,
        year_built_int=int(year) if year is not None else None,
        lat=_number(_value(attributes, config, "lat")),
        lon=_number(_value(attributes, config, "lon")),
        is_distressed=True,
        distress_type=config.distress_type,
        raw=raw,
    )


def _config_for(query: SearchQuery) -> CountyConfig | None:
    geo = query.geo if isinstance(query.geo, GeoRef) else None
    if geo and geo.county_fips in COUNTY_ENDPOINTS:
        return COUNTY_ENDPOINTS[geo.county_fips]
    normalized = query.location.casefold()
    for config in COUNTY_ENDPOINTS.values():
        if config.name.casefold() in normalized and config.state.casefold() in normalized:
            return config
    return None


class CountySource(ListingSource):
    """Configured public county foreclosure and tax-sale feeds."""

    name = "county"
    capabilities = SourceCapabilities(
        supports_distressed=True,
        supports_lease=False,
        supports_price_filter=False,
        supports_size_filter=False,
    )

    async def search(self, query: SearchQuery) -> list[Listing]:
        config = _config_for(query)
        if config is None:
            logger.info("No configured county distressed feed matches %s", query.location)
            return []
        fields = ",".join(dict.fromkeys(config.field_map.values()))
        try:
            attributes = await arcgis_query(
                config.arcgis_url,
                out_fields=fields,
                result_offset=(max(query.page, 1) - 1) * 100,
                result_count=100,
            )
        except Exception as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        listings = [map_county_listing(item, config) for item in attributes]
        if query.property_type is not None:
            listings = [
                listing
                for listing in listings
                if listing.property_type == query.property_type.value
            ]
        return listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        if ref.source != self.name:
            raise SourceError(self.name, f"County source cannot resolve {ref.source!r}")
        fips, separator, object_id = ref.source_id.partition(":")
        config = COUNTY_ENDPOINTS.get(fips)
        if not separator or config is None:
            raise SourceError(self.name, f"Invalid county reference: {ref.source_id}")
        id_field = config.field_map["id"]
        try:
            attributes = await arcgis_query(
                config.arcgis_url,
                where=f"{id_field}={object_id}",
                out_fields=",".join(dict.fromkeys(config.field_map.values())),
                result_count=1,
            )
        except Exception as exc:
            raise SourceError(self.name, str(exc), retryable=True) from exc
        if not attributes:
            raise SourceError(self.name, f"County listing not found: {ref.source_id}")
        return map_county_listing(attributes[0], config)


__all__ = ["COUNTY_ENDPOINTS", "CountyConfig", "CountySource", "map_county_listing"]
