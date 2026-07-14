"""IRS SOI migration loader tests."""

import pytest
from unittest.mock import AsyncMock

from cre_mcp.market.irs_soi import IrsSoiProvider
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_csv_loader_persists_and_maps_net_migration(tmp_path):
    provider = IrsSoiProvider(db_path=tmp_path / "market.db")
    assert await provider.load_csv(load_fixture("irs/soi_migration.csv")) == 2
    metric = await provider.net_migration("48453")
    assert metric.value == 12662
    assert metric.as_of == "2022-2023"
    assert metric.source == "IRS SOI County Migration"


@pytest.mark.asyncio
async def test_official_inflow_outflow_layout_uses_county_total_rows(tmp_path):
    provider = IrsSoiProvider(db_path=tmp_path / "official.db")
    inflow = (
        "Y2_STATEFIPS,Y2_COUNTYFIPS,Y1_STATEFIPS,Y1_COUNTYFIPS,Y1_STATE,Y1_COUNTYNAME,N1,N2,AGI\n"
        "48,453,96,000,TX,Travis County Total Migration-US and Foreign,100,220,5000\n"
    )
    outflow = (
        "Y1_STATEFIPS,Y1_COUNTYFIPS,Y2_STATEFIPS,Y2_COUNTYFIPS,Y2_STATE,Y2_COUNTYNAME,N1,N2,AGI\n"
        "48,453,96,000,TX,Travis County Total Migration-US and Foreign,80,175,4200\n"
    )
    assert await provider.load_csv(inflow, year="2022-2023") == 1
    assert await provider.load_csv(outflow, year="2022-2023") == 1
    assert (await provider.net_migration("48453")).value == 45


@pytest.mark.asyncio
async def test_net_migration_lazily_downloads_real_official_csv_layout(tmp_path):
    fetch = AsyncMock()
    fetch.get_text.side_effect = [
        load_fixture("irs/county_inflow_travis.csv"),
        load_fixture("irs/county_outflow_travis.csv"),
    ]
    provider = IrsSoiProvider(fetch=fetch, db_path=tmp_path / "live.db")

    first = await provider.net_migration("48453")
    second = await provider.net_migration("48453")

    assert first.value == -8_895
    assert first.as_of == "2022-2023"
    assert second == first
    assert fetch.get_text.await_count == 2
