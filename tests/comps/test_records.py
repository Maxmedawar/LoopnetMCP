"""County sales field mapping, spatial query, and coverage gaps."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.comps.records import (
    COUNTY_SALES_ENDPOINTS,
    map_sale_comp,
    sale_comps,
)
from cre_mcp.enrichment.counties import COUNTY_PARCEL_ENDPOINTS
from cre_mcp.models import GeoLevel, GeoRef, Listing

FIXTURES = Path(__file__).parents[1] / "fixtures" / "comps"


def _geo(fips: str) -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips=fips[:2],
        county_fips=fips,
        name="Fixture County",
    )


def _subject() -> Listing:
    return Listing(
        source="fixture",
        source_id="subject",
        name="Subject home",
        address="999 TEST RD",
        city="Greensboro",
        state="NC",
        property_type="residential",
        size_sqft_num=1_500,
        lat=35.9443,
        lon=-80.0135,
        url="https://example.test/subject",
    )


def test_live_guilford_fixture_maps_sale_comps():
    rows = json.loads((FIXTURES / "guilford_sales.json").read_text())
    config = COUNTY_PARCEL_ENDPOINTS["37081"]

    comps = [map_sale_comp(row, config, subject=_subject()) for row in rows]

    assert all(comp is not None for comp in comps)
    assert comps[0].parcel_id == "172834"
    assert comps[0].sale_price == 154_000
    assert comps[0].sale_date == "2026-07-01"
    assert comps[0].sqft == 856
    assert comps[0].distance_miles < 0.1


def test_live_yavapai_fixture_preserves_county_adjusted_price_and_centroid():
    row = json.loads((FIXTURES / "yavapai_sale.json").read_text())
    comp = map_sale_comp(row, COUNTY_PARCEL_ENDPOINTS["04025"])

    assert comp is not None
    assert comp.sale_date == "2022-12-01"
    assert comp.time_adjusted_price == 388_299
    assert comp.sqft is None
    assert comp.lat is not None and comp.lon is not None


@pytest.mark.asyncio
async def test_sale_comps_uses_shared_arcgis_radius_and_filters_candidates():
    row = json.loads((FIXTURES / "guilford_sales.json").read_text())[0]
    with patch(
        "cre_mcp.comps.records.arcgis_query",
        new=AsyncMock(return_value=[row]),
    ) as query:
        comps = await sale_comps(_geo("37081"), _subject())

    assert len(comps) == 1
    assert query.await_args.args[0].endswith("FeatureServer/0")
    assert query.await_args.kwargs["distance"] > 0
    assert query.await_args.kwargs["units"] == "esriSRUnit_Meter"
    assert query.await_args.kwargs["return_geometry"] is True


@pytest.mark.asyncio
async def test_unwired_county_returns_empty_without_network():
    with patch(
        "cre_mcp.comps.records.arcgis_query",
        new=AsyncMock(),
    ) as query:
        assert await sale_comps(_geo("17031"), _subject()) == []
    query.assert_not_awaited()


def test_phase17_maricopa_and_clark_sales_maps_are_live_and_date_tolerant():
    metro = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "enrichment" / "metro_parcels.json").read_text()
    )
    maricopa = map_sale_comp(metro["04013"], COUNTY_PARCEL_ENDPOINTS["04013"])
    clark = map_sale_comp(metro["32003"], COUNTY_PARCEL_ENDPOINTS["32003"])

    assert maricopa is not None and maricopa.sale_price == 103_846
    assert maricopa.sale_date == "2010-08-01"
    assert clark is not None and clark.sale_price == 110_000
    assert clark.sale_date == "2011-01-01"


def test_phase23_live_king_wake_and_franklin_sales_layers_map():
    rows = json.loads((FIXTURES / "phase23_sales.json").read_text())

    king = map_sale_comp(rows["53033"], COUNTY_SALES_ENDPOINTS["53033"])
    wake = map_sale_comp(rows["37183"], COUNTY_SALES_ENDPOINTS["37183"])
    franklin = map_sale_comp(rows["39049"], COUNTY_SALES_ENDPOINTS["39049"])

    assert set(COUNTY_SALES_ENDPOINTS) == {"53033", "37183", "39049"}
    assert king is not None and king.sale_price == 760_000
    assert king.sale_date == "2023-08-16"
    assert wake is not None and wake.sqft == 2_163
    assert wake.units == 1
    assert wake.sale_date == "2024-12-16"
    assert franklin is not None and franklin.parcel_id == "010-283587"
    assert franklin.sale_date == "2025-07-16"


@pytest.mark.asyncio
async def test_phase23_new_county_uses_its_verified_spatial_sales_layer():
    row = json.loads((FIXTURES / "phase23_sales.json").read_text())["37183"]
    subject = _subject().model_copy(
        update={"lat": 35.543, "lon": -78.685, "address": "999 OTHER RD"}
    )
    with patch(
        "cre_mcp.comps.records.arcgis_query",
        new=AsyncMock(return_value=[row]),
    ) as query:
        comps = await sale_comps(_geo("37183"), subject)

    assert len(comps) == 1
    assert query.await_args.args[0] == COUNTY_SALES_ENDPOINTS["37183"].sales_layer
    assert "TOTSALPRICE" in query.await_args.kwargs["out_fields"]
