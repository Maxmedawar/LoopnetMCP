import json
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.models import GeoLevel, GeoRef
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.distressed.county import (
    COUNTY_ENDPOINTS,
    CountySource,
    map_county_listing,
)
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_county_source_selects_config_and_maps_declared_fields():
    attributes = [
        json.loads(load_fixture("county/guilford.json"))["features"][0]["attributes"]
    ]
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="37",
        county_fips="37081",
        name="Guilford County, NC",
    )
    with patch(
        "cre_mcp.sources.distressed.county.arcgis_query",
        new=AsyncMock(return_value=attributes),
    ) as query:
        listings = await CountySource().search(
            SearchQuery(location="Guilford County, NC", geo=geo)
        )

    assert len(listings) == 1
    assert listings[0].source_id == "37081:1"
    assert listings[0].distress_type == "foreclosure"
    assert listings[0].size_sqft_num == 2_040
    assert listings[0].raw["assessed_value"] == 322_800
    assert "ForeclosuresPublic" in query.await_args.args[0]


@pytest.mark.asyncio
async def test_county_source_skips_unconfigured_geo_gracefully():
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )
    with patch(
        "cre_mcp.sources.distressed.county.arcgis_query",
        new=AsyncMock(),
    ) as query:
        result = await CountySource().search(
            SearchQuery(location="Travis County, TX", geo=geo)
        )
    assert result == []
    query.assert_not_awaited()


@pytest.mark.parametrize(
    ("fixture", "fips", "expected_price"),
    [
        ("county/yavapai.json", "04025", 2_293.77),
        ("county/douglas.json", "08035", 185.04),
    ],
)
def test_tax_sale_county_field_maps_match_live_fixtures(
    fixture,
    fips,
    expected_price,
):
    attributes = json.loads(load_fixture(fixture))["features"][0]["attributes"]
    listing = map_county_listing(attributes, COUNTY_ENDPOINTS[fips])

    assert listing.source_id.startswith(f"{fips}:")
    assert listing.distress_type == "tax_sale"
    assert listing.price_usd == pytest.approx(expected_price)
