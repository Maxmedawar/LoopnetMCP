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


def test_all_three_verified_counties_declare_complete_mapping_contract():
    assert set(COUNTY_PARCEL_ENDPOINTS) == {"37081", "04025", "08035"}
    for config in COUNTY_PARCEL_ENDPOINTS.values():
        assert REQUIRED_FIELDS <= config.field_map.keys()
        assert config.arcgis_url.endswith(("FeatureServer/0", "MapServer/0"))


def test_only_live_confirmed_counties_declare_sales_layers():
    assert COUNTY_PARCEL_ENDPOINTS["37081"].sales_layer.endswith("FeatureServer/0")
    assert COUNTY_PARCEL_ENDPOINTS["04025"].sales_layer.endswith("FeatureServer/5")
    assert COUNTY_PARCEL_ENDPOINTS["08035"].sales_layer is None


def test_config_selection_uses_resolved_county_fips_and_skips_unknown():
    assert config_for_geo(_geo("08035")) is COUNTY_PARCEL_ENDPOINTS["08035"]
    assert config_for_geo(_geo("48453")) is None
    assert config_for_geo(None) is None


def test_douglas_live_field_map_populates_available_values_only():
    attributes = json.loads((FIXTURES / "douglas_parcel.json").read_text())
    parcel = map_parcel(attributes, COUNTY_PARCEL_ENDPOINTS["08035"])

    assert parcel.apn == "235103106018"
    assert parcel.site_address == "535 1ST AVE, CASTLE ROCK, CO, 80108"
    assert parcel.assessed_value == 907_962
    assert parcel.last_sale_price is None
    assert parcel.land_value is None
