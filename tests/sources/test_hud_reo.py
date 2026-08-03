import json
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.models import GeoLevel, GeoRef, ListingRef
from cre_mcp.sources.base import SearchQuery
from cre_mcp.sources.distressed.hud_reo import HudReoSource
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_hud_reo_arcgis_fixture_maps_distressed_listings():
    attributes = [
        item["attributes"]
        for item in json.loads(load_fixture("hud_reo/search_response.json"))["features"]
    ]
    with patch(
        "cre_mcp.sources.distressed.hud_reo.arcgis_query",
        new=AsyncMock(return_value=attributes),
    ) as query:
        listings = await HudReoSource().search(SearchQuery(location="TX"))

    assert len(listings) == 2
    assert listings[0].source == "hud_reo"
    assert listings[0].source_id == "512-485170"
    assert listings[0].is_distressed is True
    assert listings[0].distress_type == "reo"
    assert listings[0].lat == pytest.approx(30.142231)
    assert listings[0].raw["CASE_NUM"] == "512-485170"
    assert query.await_args.kwargs["where"] == "STATE_CODE='TX'"


@pytest.mark.asyncio
async def test_hud_reo_detail_uses_same_enriched_mapping():
    attributes = [
        json.loads(load_fixture("hud_reo/search_response.json"))["features"][0][
            "attributes"
        ]
    ]
    with patch(
        "cre_mcp.sources.distressed.hud_reo.arcgis_query",
        new=AsyncMock(return_value=attributes),
    ) as query:
        listing = await HudReoSource().get_detail(
            ListingRef(source="hud_reo", source_id="512-485170")
        )
    assert listing.source_id == "512-485170"
    assert query.await_args.kwargs["where"] == "CASE_NUM='512-485170'"


@pytest.mark.asyncio
async def test_hud_reo_configured_county_uses_census_bounding_box():
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="37",
        county_fips="37081",
        name="Guilford County, NC",
    )
    with patch(
        "cre_mcp.sources.distressed.hud_reo.arcgis_query",
        new=AsyncMock(return_value=[]),
    ) as query:
        await HudReoSource().search(
            SearchQuery(location="Guilford County, NC", geo=geo)
        )
    assert query.await_args.kwargs["where"] == "STATE_CODE='NC'"
    assert query.await_args.kwargs["geometry"]["xmin"] == pytest.approx(-80.046869)
