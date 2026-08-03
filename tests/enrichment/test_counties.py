"""County parcel registry selection and field-map coverage."""

import json
from pathlib import Path

from cre_mcp.enrichment.arcgis import map_parcel
from cre_mcp.enrichment.counties import COUNTY_PARCEL_ENDPOINTS, config_for_geo
from cre_mcp.models import GeoLevel, GeoRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "enrichment"
REQUIRED_FIELDS = {
    "apn",
    "owner_name",
    "owner_mailing_addr",
    "site_addr",
    "assessed_value",
    "last_sale_price",
    "last_sale_date",
    "land_value",
    "year_built",
    "use_code",
}


def _geo(fips: str) -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips=fips[:2],
        county_fips=fips,
        name="Test County",
    )


def test_all_thirteen_verified_counties_declare_complete_mapping_contract():
    assert set(COUNTY_PARCEL_ENDPOINTS) == {
        "04013",
        "04025",
        "08035",
        "12011",
        "12086",
        "13121",
        "32003",
        "37081",
        "37119",
        "48029",
        "48113",
        "48201",
        "48453",
    }
    for config in COUNTY_PARCEL_ENDPOINTS.values():
        assert REQUIRED_FIELDS <= config.field_map.keys()
        assert "/FeatureServer/" in config.arcgis_url or "/MapServer/" in config.arcgis_url


def test_only_live_confirmed_counties_declare_sales_layers():
    assert COUNTY_PARCEL_ENDPOINTS["37081"].sales_layer.endswith("FeatureServer/0")
    assert COUNTY_PARCEL_ENDPOINTS["04025"].sales_layer.endswith("FeatureServer/5")
    assert COUNTY_PARCEL_ENDPOINTS["08035"].sales_layer is None
    assert {
        fips for fips, config in COUNTY_PARCEL_ENDPOINTS.items() if config.sales_layer
    } == {"04013", "04025", "32003", "37081"}


def test_config_selection_uses_resolved_county_fips_and_skips_unknown():
    assert config_for_geo(_geo("08035")) is COUNTY_PARCEL_ENDPOINTS["08035"]
    assert config_for_geo(_geo("17031")) is None
    assert config_for_geo(None) is None


def test_douglas_live_field_map_populates_available_values_only():
    attributes = json.loads((FIXTURES / "douglas_parcel.json").read_text())
    parcel = map_parcel(attributes, COUNTY_PARCEL_ENDPOINTS["08035"])

    assert parcel.apn == "235103106018"
    assert parcel.site_address == "535 1ST AVE, CASTLE ROCK, CO, 80108"
    assert parcel.assessed_value == 907_962
    assert parcel.last_sale_price is None
    assert parcel.land_value is None


def test_phase17_live_metro_fixtures_map_owner_parcel_and_available_sale_fields():
    samples = json.loads((FIXTURES / "metro_parcels.json").read_text())

    for fips, attributes in samples.items():
        parcel = map_parcel(attributes, COUNTY_PARCEL_ENDPOINTS[fips])
        assert parcel.apn
        assert parcel.owner_name
        assert parcel.site_address

    assert map_parcel(samples["48453"], COUNTY_PARCEL_ENDPOINTS["48453"]).owner_name == (
        "AUSTIN IRON HOLDINGS LLC"
    )
    clark = map_parcel(samples["32003"], COUNTY_PARCEL_ENDPOINTS["32003"])
    assert clark.last_sale_price == 110_000
    assert clark.last_sale_date == "2011-01-01"
    mecklenburg = map_parcel(samples["37119"], COUNTY_PARCEL_ENDPOINTS["37119"])
    assert mecklenburg.owner_name == "CLARLISSA MAE PONDS"
    assert mecklenburg.last_sale_price == 362_000
