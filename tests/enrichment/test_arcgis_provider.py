"""ArcGIS assessor provider mapping and query construction."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.config import CreConfig
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
    sale = {
        "PACKAGE_SALE_PRICE": 2_450_000,
        "PACKAGE_SALE_DATE": 1648684800000,
    }
    with patch("cre_mcp.enrichment.arcgis.require_source"), patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(side_effect=[[attributes], [sale]]),
    ) as query:
        provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["37081"])
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
    assert parcel.last_sale_price == 2_450_000
    assert parcel.year_built == 1983
    parcel_query, sale_query = query.await_args_list
    assert parcel_query.kwargs["where"] == "UPPER(LOCATION_ADDR) LIKE '%100 A S ELM%'"
    assert parcel_query.kwargs["result_count"] == 1
    assert "UPPER(REID)='1'" in sale_query.kwargs["where"]
    assert sale_query.kwargs["order_by_fields"] == "PACKAGE_SALE_DATE DESC"


@pytest.mark.asyncio
async def test_apn_query_maps_live_yavapai_feature():
    attributes = json.loads((FIXTURES / "yavapai_parcel.json").read_text())
    with patch("cre_mcp.enrichment.arcgis.require_source"), patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(side_effect=[[attributes], []]),
    ) as query:
        provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["04025"])
        parcel = await provider.lookup(None, "1320514277023", _geo("04025", "04"))

    assert parcel is not None
    assert parcel.owner_name == "REDDY LIVING TRUST"
    assert parcel.owner_mailing_address == "1834 MEADOWS CIR, ROCKFORD, IL, 611081504"
    assert parcel.site_address == "975 E TERRITORIAL TRL, AZ"
    assert parcel.use_code == "RCU-175"
    assert query.await_args_list[0].kwargs["where"] == (
        "UPPER(PARCEL_ID)='1320514277023'"
    )


@pytest.mark.asyncio
async def test_no_matching_feature_returns_none():
    provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["08035"])
    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[]),
    ):
        assert await provider.lookup("999 Missing Road", None, _geo("08035", "08")) is None


@pytest.mark.asyncio
async def test_travis_address_query_matches_live_owner_fixture_with_contains_prefix():
    samples = json.loads((FIXTURES / "metro_parcels.json").read_text())
    provider = ArcgisParcelProvider(COUNTY_PARCEL_ENDPOINTS["48453"])
    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[samples["48453"]]),
    ) as query:
        parcel = await provider.lookup(
            "9606 Old Manor Road, Austin, TX 78724",
            None,
            _geo("48453", "48"),
        )

    assert parcel is not None
    assert parcel.owner_name == "AUSTIN IRON HOLDINGS LLC"
    assert parcel.site_address == "9606 OLD MANOR RD TX 78724"
    assert query.await_args.kwargs["where"] == (
        "UPPER(situs_address) LIKE '%9606 OLD MANOR%'"
    )


@pytest.mark.asyncio
async def test_maricopa_parcel_only_neither_fetches_nor_retains_sale_fields():
    attributes = json.loads((FIXTURES / "metro_parcels.json").read_text())["04013"]
    runtime = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"parcel.maricopa_04013": True},
    )
    provider = ArcgisParcelProvider(
        COUNTY_PARCEL_ENDPOINTS["04013"],
        runtime_config=runtime,
    )

    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(return_value=[attributes]),
    ) as query:
        parcel = await provider.lookup(None, "304-31-091", _geo("04013", "04"))

    assert parcel is not None
    assert parcel.last_sale_price is None
    assert parcel.last_sale_date is None
    assert "SALE_PRICE" not in query.await_args.kwargs["out_fields"]
    assert "SALE_DATE" not in query.await_args.kwargs["out_fields"]
    assert "SALE_PRICE" not in parcel.raw
    assert "SALE_DATE" not in parcel.raw
    query.assert_awaited_once()


@pytest.mark.asyncio
async def test_maricopa_sale_fields_are_included_only_with_both_toggles():
    attributes = json.loads((FIXTURES / "metro_parcels.json").read_text())["04013"]
    runtime = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={
            "parcel.maricopa_04013": True,
            "sales.maricopa_04013": True,
        },
    )
    provider = ArcgisParcelProvider(
        COUNTY_PARCEL_ENDPOINTS["04013"],
        runtime_config=runtime,
    )

    with patch(
        "cre_mcp.enrichment.arcgis.arcgis_query",
        new=AsyncMock(side_effect=[[attributes], []]),
    ) as query:
        parcel = await provider.lookup(None, "304-31-091", _geo("04013", "04"))

    assert parcel is not None
    assert parcel.last_sale_price == 103_846
    assert "SALE_PRICE" in query.await_args_list[0].kwargs["out_fields"]
    assert "SALE_DATE" in query.await_args_list[0].kwargs["out_fields"]
