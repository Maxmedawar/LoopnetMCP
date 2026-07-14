"""Verified public county assessor parcel endpoints."""

from dataclasses import dataclass, field

from cre_mcp.models.geo import GeoRef


@dataclass(frozen=True)
class CountyParcelConfig:
    """ArcGIS layer and source-specific field mapping for one county."""

    fips: str
    name: str
    state: str
    arcgis_url: str
    field_map: dict[str, str | None]
    sales_layer: str | None = None
    sales_field_map: dict[str, str | None] = field(default_factory=dict)
    sales_where: str = "1=1"


COUNTY_PARCEL_ENDPOINTS: dict[str, CountyParcelConfig] = {
    "37081": CountyParcelConfig(
        fips="37081",
        name="Guilford County",
        state="NC",
        arcgis_url=(
            "https://gcgis.guilfordcountync.gov/arcgis/rest/services/Tax/"
            "PublishingParcelsSpatialView_FeatureToPointWGS84/FeatureServer/0"
        ),
        field_map={
            "apn": "REID",
            "owner_name": "Owner",
            "owner_mailing_addr": "Mail_Address",
            "owner_mailing_city": "Mail_City",
            "owner_mailing_state": "Mail_State",
            "owner_mailing_zip": "Mail_Zip",
            "site_addr": "LOCATION_ADDR",
            "site_city": None,
            "site_state": None,
            "site_zip": None,
            "assessed_value": "Total_Assessed",
            "building_sqft": "Structure_Size",
            "units": None,
            "last_sale_price": None,
            "last_sale_date": "DEED_DATE",
            "land_value": "Total_Land_Value",
            "year_built": "YEAR_BUILT",
            "use_code": "Property_Type",
            "lat": "CentroidYCoordinat",
            "lon": "CentroidXCoordinate",
        },
        sales_layer=(
            "https://gcgis.guilfordcountync.gov/arcgis/rest/services/Tax/"
            "GCCadastral_FeatureToPointWGS84/FeatureServer/0"
        ),
        sales_field_map={
            "parcel_id": "REID",
            "address": "SITUS_ADDRESS",
            "sale_price": "PACKAGE_SALE_PRICE",
            "time_adjusted_price": None,
            "sale_date": "PACKAGE_SALE_DATE",
            "sqft": "HEATED_AREA",
            "units": "TOTAL_UNITS",
            "use_code": "BUILDING_DESCRIPTION",
            "lat": "CentroidYCoordinat",
            "lon": "CentroidXCoordinate",
        },
        sales_where=(
            "PACKAGE_SALE_PRICE > 10000 AND PACKAGE_SALE_DATE IS NOT NULL "
            "AND SALE_PRICE_SOURCE = 'REV'"
        ),
    ),
    "04025": CountyParcelConfig(
        fips="04025",
        name="Yavapai County",
        state="AZ",
        arcgis_url=(
            "https://services1.arcgis.com/BajuNXbtZNiBKFkx/ArcGIS/rest/services/"
            "Parcels_WGS84/FeatureServer/0"
        ),
        field_map={
            "apn": "PARCEL_ID",
            "owner_name": "NAME",
            "owner_mailing_addr": "ADDRESS",
            "owner_mailing_city": "CITY",
            "owner_mailing_state": "STATE",
            "owner_mailing_zip": "ZIP",
            "site_addr": "SITUS_ADD_DOR",
            "site_city": None,
            "site_state": None,
            "site_zip": None,
            "assessed_value": None,
            "building_sqft": None,
            "units": None,
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": None,
            "year_built": None,
            "use_code": "ZONING",
            "lat": None,
            "lon": None,
        },
        sales_layer=(
            "https://services1.arcgis.com/BajuNXbtZNiBKFkx/ArcGIS/rest/services/"
            "ASR_Recent_Sales_5_years/FeatureServer/5"
        ),
        sales_field_map={
            "parcel_id": "PARCELNO",
            "address": "PARLABEL",
            "sale_price": "SALEPRICE",
            "time_adjusted_price": "TIMEADJSALEPRICE",
            "sale_date": "SALEDATE",
            "sqft": None,
            "units": None,
            "use_code": "AFFTYPE",
            "lat": None,
            "lon": None,
        },
        sales_where="SALEPRICE > 10000 AND CNT = 1 AND MISMATCH = 0",
    ),
    "08035": CountyParcelConfig(
        fips="08035",
        name="Douglas County",
        state="CO",
        arcgis_url=(
            "https://services.arcgis.com/seTexOicoRXDvRsJ/ArcGIS/rest/services/"
            "Parcels_Enriched/FeatureServer/0"
        ),
        field_map={
            "apn": "STATE_PARCEL_NO",
            "owner_name": "OWNER_NAME",
            "owner_mailing_addr": "MAILING_ADDRESS_LINE_1",
            "owner_mailing_city": "MAILING_CITY_NAME",
            "owner_mailing_state": "MAILING_STATE",
            "owner_mailing_zip": "MAILING_ZIP_CODE",
            "site_addr": "LOCATION_ADDRESS",
            "site_city": "CITY_NAME",
            "site_state": "LOCATION_STATE_CODE",
            "site_zip": "LOCATION_ZIP_CODE",
            "assessed_value": "TOTAL_ACTUAL_VALUE",
            "building_sqft": None,
            "units": None,
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": None,
            "year_built": None,
            "use_code": "PARCEL_TYPE",
            "lat": "LATITUDE",
            "lon": "LONGITUDE",
        },
    ),
}


def config_for_geo(geo: GeoRef | None) -> CountyParcelConfig | None:
    """Select the configured county assessor layer for a resolved geography."""
    if geo is None or geo.county_fips is None:
        return None
    return COUNTY_PARCEL_ENDPOINTS.get(geo.county_fips)


__all__ = ["COUNTY_PARCEL_ENDPOINTS", "CountyParcelConfig", "config_for_geo"]
