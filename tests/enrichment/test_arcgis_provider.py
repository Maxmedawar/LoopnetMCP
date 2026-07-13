"""ArcGIS assessor provider mapping and query construction."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.enrichment.arcgis import ArcgisParcelProvider
from cre_mcp.enrichment.counties import COUNTY_PARCEL_ENDPOINTS
from cre_mcp.models import GeoLevel, GeoRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "enrichment"


def _geo(fips: str, state_fips: str) -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips=state_fips,
        county_fips=fips,
        name="Test County",
    )


@pytest.mark.asyncio
async def test_address_query_maps_live_guilford_feature():
    attributes = json.loads((FIXTURES / "guilford_parcel.json").read_text())
    provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["37081"])

    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[attributes]),
    ) as query:
        parcel = await provider.lookup(
            "100 A S Elm Street, Greensboro, NC 27401",
            None,
            _geo("37081", "37"),
        )

    assert parcel is not None
    assert parcel.apn == "1"
    assert parcel.owner_name == "SIT-IN MOVEMENT INC"
    assert parcel.assessed_value == 7_987_248
    assert parcel.land_value == 2_909_800
    assert parcel.last_sale_date == "2022-03-31"
    assert parcel.year_built == 1983
    assert query.await_args.kwargs["where"] == "UPPER(LOCATION_ADDR)='100 A S ELM ST'"
    assert query.await_args.kwargs["result_count"] == 1


@pytest.mark.asyncio
async def test_apn_query_maps_live_yavapai_feature():
    attributes = json.loads((FIXTURES / "yavapai_parcel.json").read_text())
    provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["04025"])

    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[attributes]),
    ) as query:
        parcel = await provider.lookup(None, "1320514277023", _geo("04025", "04"))

    assert parcel is not None
    assert parcel.owner_name == "REDDY LIVING TRUST"
    assert parcel.owner_mailing_address == "1834 MEADOWS CIR, ROCKFORD, IL, 611081504"
    assert parcel.site_address == "975 E TERRITORIAL TRL, AZ"
    assert parcel.use_code == "RCU-175"
    assert query.await_args.kwargs["where"] == "UPPER(PARCEL_ID)='1320514277023'"


@pytest.mark.asyncio
async def test_no_matching_feature_returns_none():
    provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["08035"])
    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[]),
    ):
        assert await provider.lookup("999 Missing Road", None, _geo("08035", "08")) is None
