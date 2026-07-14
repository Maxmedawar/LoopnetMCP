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
    address_number_field: str | None = None
    address_street_field: str | None = None


COUNTY_PARCEL_ENDPOINTS: dict[str, CountyParcelConfig] = {
    "48453": CountyParcelConfig(
        fips="48453",
        name="Travis County",
        state="TX",
        arcgis_url=(
            "https://taxmaps.traviscountytx.gov/arcgis/rest/services/"
            "Parcels/FeatureServer/0"
        ),
        field_map={
            "apn": "PROP_ID",
            "owner_name": "py_owner_name",
            "owner_mailing_addr": "py_address",
            "owner_mailing_city": None,
            "owner_mailing_state": None,
            "owner_mailing_zip": None,
            "site_addr": "situs_address",
            "site_city": None,
            "site_state": None,
            "site_zip": "situs_zip",
            "assessed_value": "market_value",
            "building_sqft": None,
            "units": None,
            "last_sale_price": None,
            "last_sale_date": "deed_date",
            "land_value": None,
            "year_built": "F1year_imprv",
            "use_code": "land_type_desc",
            "lat": None,
            "lon": None,
        },
    ),
    "48201": CountyParcelConfig(
        fips="48201",
        name="Harris County",
        state="TX",
        arcgis_url=(
            "https://services.arcgis.com/su8ic9KbA7PYVxPS/ArcGIS/rest/services/"
            "Harris_County_Parcels/FeatureServer/1"
        ),
        field_map={
            "apn": "HCAD_NUM",
            "owner_name": "owner_name_1",
            "owner_mailing_addr": "mail_addr_1",
            "owner_mailing_city": "mail_city",
            "owner_mailing_state": "mail_state",
            "owner_mailing_zip": "mail_zip",
            "site_addr": None,
            "site_number": "site_str_num",
            "site_pre_dir": "site_str_pfx",
            "site_street": "site_str_name",
            "site_suffix": "site_str_sfx",
            "site_post_dir": "site_str_sfx_dir",
            "site_unit": None,
            "site_city": "site_city",
            "site_state": None,
            "site_zip": "site_zip",
            "assessed_value": "total_market_val",
            "building_sqft": None,
            "units": None,
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": "land_value",
            "year_built": None,
            "use_code": "state_class",
            "lat": None,
            "lon": None,
        },
        address_number_field="site_str_num",
        address_street_field="site_str_name",
    ),
    "48113": CountyParcelConfig(
        fips="48113",
        name="Dallas County",
        state="TX",
        arcgis_url=(
            "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/"
            "DallasTaxParcels/FeatureServer/0"
        ),
        field_map={
            "apn": "ACCT",
            "owner_name": "TAXPANAME1",
            "owner_mailing_addr": "TAXPAADD2",
            "owner_mailing_city": "TAXPACITY",
            "owner_mailing_state": "TAXPASTA",
            "owner_mailing_zip": "TAXPAZIP",
            "site_addr": None,
            "site_number": "ST_NUM",
            "site_pre_dir": "ST_DIR",
            "site_street": "ST_NAME",
            "site_suffix": "ST_TYPE",
            "site_post_dir": None,
            "site_unit": "UNITID",
            "site_city": "CITY",
            "site_state": None,
            "site_zip": None,
            "assessed_value": None,
            "building_sqft": None,
            "units": None,
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": None,
            "year_built": None,
            "use_code": "PROP_CL",
            "lat": None,
            "lon": None,
        },
        address_number_field="ST_NUM",
        address_street_field="ST_NAME",
    ),
    "48029": CountyParcelConfig(
        fips="48029",
        name="Bexar County",
        state="TX",
        arcgis_url=(
            "https://gis.sara-tx.org/ags1/rest/services/FW_Bexar/"
            "BCAD_Parcels_PROD/FeatureServer/0"
        ),
        field_map={
            "apn": "Geo_id",
            "owner_name": "Owner_name",
            "owner_mailing_addr": "Addr_line2",
            "owner_mailing_city": "Addr_city",
            "owner_mailing_state": "Addr_state",
            "owner_mailing_zip": "Zip",
            "site_addr": "Situs",
            "site_city": "City",
            "site_state": None,
            "site_zip": "Situs_Zip",
            "assessed_value": "Market_val",
            "building_sqft": "Sq_ft",
            "units": "Num_Units",
            "last_sale_price": None,
            "last_sale_date": "Last_Deed_Date",
            "land_value": None,
            "year_built": "Yr_blt",
            "use_code": "Property_use_cd",
            "lat": None,
            "lon": None,
        },
    ),
    "04013": CountyParcelConfig(
        fips="04013",
        name="Maricopa County",
        state="AZ",
        arcgis_url=(
            "https://services.arcgis.com/ykpntM6e3tHvzKRJ/arcgis/rest/services/"
            "Parcels_view/FeatureServer/0"
        ),
        field_map={
            "apn": "APN_DASH",
            "owner_name": "OWNER_NAME",
            "owner_mailing_addr": "MAIL_ADDR1",
            "owner_mailing_city": "MAIL_CITY",
            "owner_mailing_state": "MAIL_STATE",
            "owner_mailing_zip": "MAIL_ZIP",
            "site_addr": "PHYSICAL_ADDRESS",
            "site_city": None,
            "site_state": None,
            "site_zip": None,
            "assessed_value": "FCV_CUR",
            "building_sqft": "LIVING_SPACE",
            "units": None,
            "last_sale_price": "SALE_PRICE",
            "last_sale_date": "SALE_DATE",
            "land_value": None,
            "year_built": "CONST_YEAR",
            "use_code": "PUC",
            "lat": "LATITUDE",
            "lon": "LONGITUDE",
        },
        sales_layer=(
            "https://services.arcgis.com/ykpntM6e3tHvzKRJ/arcgis/rest/services/"
            "Parcels_view/FeatureServer/0"
        ),
        sales_field_map={
            "parcel_id": "APN_DASH",
            "address": "PHYSICAL_ADDRESS",
            "sale_price": "SALE_PRICE",
            "time_adjusted_price": None,
            "sale_date": "SALE_DATE",
            "sqft": "LIVING_SPACE",
            "units": None,
            "use_code": "PUC",
            "lat": "LATITUDE",
            "lon": "LONGITUDE",
        },
        sales_where="SALE_PRICE > 10000 AND SALE_DATE IS NOT NULL",
    ),
    "32003": CountyParcelConfig(
        fips="32003",
        name="Clark County",
        state="NV",
        arcgis_url=(
            "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/"
            "AOExtract_New/FeatureServer/10"
        ),
        field_map={
            "apn": "PARCEL",
            "owner_name": "OWNER",
            "owner_mailing_addr": "MAIL_ADDRESS1",
            "owner_mailing_city": "MAIL_CITY",
            "owner_mailing_state": "MAIL_STATE",
            "owner_mailing_zip": "MAIL_ZIPCODE",
            "site_addr": None,
            "site_number": "LOC_STRNO",
            "site_pre_dir": "LOC_STRDIR",
            "site_street": "LOC_STRNAME",
            "site_suffix": "LOC_STRTYPE",
            "site_post_dir": None,
            "site_unit": "LOC_STRUNIT",
            "site_city": "LOC_CITY",
            "site_state": None,
            "site_zip": None,
            "assessed_value": "TOTVAL",
            "building_sqft": None,
            "units": None,
            "last_sale_price": "SALEPRICE",
            "last_sale_date": "SALEDATE",
            "land_value": "LANDVAL",
            "year_built": "CONSTYR",
            "use_code": "LANDUSE",
            "lat": None,
            "lon": None,
        },
        sales_layer=(
            "https://services1.arcgis.com/F1v0ufATbBQScMtY/arcgis/rest/services/"
            "CC_PARCELS_SHP/FeatureServer/1"
        ),
        sales_field_map={
            "parcel_id": "PARCEL",
            "address": "ADDRESS",
            "sale_price": "SALEPRICE",
            "time_adjusted_price": None,
            "sale_date": "SALEDATE",
            "sqft": None,
            "units": None,
            "use_code": "LANDUSE",
            "lat": None,
            "lon": None,
        },
        sales_where="SALEPRICE > 10000 AND SALEDATE >= '20210101'",
        address_number_field="LOC_STRNO",
        address_street_field="LOC_STRNAME",
    ),
    "12086": CountyParcelConfig(
        fips="12086",
        name="Miami-Dade County",
        state="FL",
        arcgis_url=(
            "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/"
            "ParcelsView_gdb/FeatureServer/0"
        ),
        field_map={
            "apn": "FOLIO",
            "owner_name": "TRUE_OWNER1",
            "owner_mailing_addr": "TRUE_MAILING_ADDR1",
            "owner_mailing_city": "TRUE_MAILING_CITY",
            "owner_mailing_state": "TRUE_MAILING_STATE",
            "owner_mailing_zip": "TRUE_MAILING_ZIP_CODE",
            "site_addr": "TRUE_SITE_ADDR",
            "site_city": "TRUE_SITE_CITY",
            "site_state": None,
            "site_zip": "TRUE_SITE_ZIP_CODE",
            "assessed_value": None,
            "building_sqft": "BUILDING_ACTUAL_AREA",
            "units": None,
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": None,
            "year_built": "YEAR_BUILT",
            "use_code": None,
            "lat": None,
            "lon": None,
        },
    ),
    "12011": CountyParcelConfig(
        fips="12011",
        name="Broward County",
        state="FL",
        arcgis_url=(
            "https://services.arcgis.com/JMAJrTsHNLrSsWf5/arcgis/rest/services/"
            "PARCEL_POLY_BCPA_TAXROLL/FeatureServer/0"
        ),
        field_map={
            "apn": "FOLIO_NUMBER",
            "owner_name": "NAME_LINE_1",
            "owner_mailing_addr": "ADDRESS_LINE_1",
            "owner_mailing_city": "CITY",
            "owner_mailing_state": "STATE",
            "owner_mailing_zip": "ZIP",
            "site_addr": None,
            "site_number": "SITUS_STREET_NUMBER",
            "site_pre_dir": "SITUS_STREET_DIRECTION",
            "site_street": "SITUS_STREET_NAME",
            "site_suffix": "SITUS_STREET_TYPE",
            "site_post_dir": "SITUS_STREET_POST_DIR",
            "site_unit": "SITUS_UNIT_NUMBER",
            "site_city": "SITUS_CITY",
            "site_state": None,
            "site_zip": "SITUS_ZIP_CODE",
            "assessed_value": "LY_JUSTVAL",
            "building_sqft": "BLDG_TOT_SQ_FOOTAGE",
            "units": "BLDG_UNITS",
            "last_sale_price": None,
            "last_sale_date": "SALE_DATE_1",
            "land_value": "JUST_LAND_VALUE",
            "year_built": "ACTUAL_YEAR_BUILT",
            "use_code": "USE_CODE",
            "lat": None,
            "lon": None,
        },
        address_number_field="SITUS_STREET_NUMBER",
        address_street_field="SITUS_STREET_NAME",
    ),
    "13121": CountyParcelConfig(
        fips="13121",
        name="Fulton County",
        state="GA",
        arcgis_url=(
            "https://gismaps.fultoncountyga.gov/arcgispub2/rest/services/"
            "Tax/Tyler_TaxParcels/MapServer/0"
        ),
        field_map={
            "apn": "ParcelID",
            "owner_name": "Owner",
            "owner_mailing_addr": "OwnerAddr1",
            "owner_mailing_city": "OwnerAddr2",
            "owner_mailing_state": None,
            "owner_mailing_zip": None,
            "site_addr": "Address",
            "site_city": None,
            "site_state": None,
            "site_zip": None,
            "assessed_value": None,
            "building_sqft": None,
            "units": "LivUnits",
            "last_sale_price": None,
            "last_sale_date": None,
            "land_value": None,
            "year_built": None,
            "use_code": "LUCode",
            "lat": None,
            "lon": None,
        },
    ),
    "37119": CountyParcelConfig(
        fips="37119",
        name="Mecklenburg County",
        state="NC",
        arcgis_url=(
            "https://gis.charlottenc.gov/arcgis/rest/services/"
            "CLT_Ex/CLTEx_MoreInfo/MapServer/4"
        ),
        field_map={
            "apn": "PID",
            "owner_name": None,
            "owner_name_1": "Owner_FirstName",
            "owner_name_2": "Owner_LastName",
            "owner_mailing_addr": "Mailing_Address",
            "owner_mailing_city": "City",
            "owner_mailing_state": "State",
            "owner_mailing_zip": "Zip_Code",
            "site_addr": "Location",
            "site_city": None,
            "site_state": None,
            "site_zip": None,
            "assessed_value": "Total_Value",
            "building_sqft": "Heated_Sqft",
            "units": "Units",
            "last_sale_price": "Price",
            "last_sale_date": "Sales_Date",
            "land_value": "Land_Value",
            "year_built": "Year_Built",
            "use_code": "Property_Use",
            "lat": None,
            "lon": None,
        },
    ),
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
