"""IRS SOI migration loader tests."""

import pytest
from unittest.mock import AsyncMock

from cre_mcp.config import CreConfig
from cre_mcp.market.irs_soi import IrsSoiProvider
from tests.conftest import load_fixture, write_cached_rights_registry


def _config(
    tmp_path,
    db_name: str = "market.db",
    *,
    ttl_seconds: int = 3_600,
) -> CreConfig:
    return CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / db_name,
        source_rights_registry_path=write_cached_rights_registry(
            tmp_path,
            {"market.irs_soi_migration"},
            ttl_seconds=ttl_seconds,
        ),
        source_rights_enabled={"market.irs_soi_migration": True},
    )


@pytest.mark.asyncio
async def test_csv_loader_persists_and_maps_net_migration(tmp_path):
    config = _config(tmp_path)
    provider = IrsSoiProvider(config=config, db_path=config.cache_db_path)
    assert await provider.load_csv(load_fixture("irs/soi_migration.csv")) == 2
    metric = await provider.net_migration("48453")
    assert metric.value == 12662
    assert metric.as_of == "2022-2023"
    assert metric.source == "IRS SOI County Migration"


@pytest.mark.asyncio
async def test_official_inflow_outflow_layout_uses_county_total_rows(tmp_path):
    config = _config(tmp_path, "official.db")
    provider = IrsSoiProvider(config=config, db_path=config.cache_db_path)
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
    config = _config(tmp_path, "live.db")
    provider = IrsSoiProvider(
        config=config,
        fetch=fetch,
        db_path=config.cache_db_path,
    )

    first = await provider.net_migration("48453")
    second = await provider.net_migration("48453")

    assert first.value == -8_895
    assert first.as_of == "2022-2023"
    assert second == first
    assert fetch.get_text.await_count == 2


@pytest.mark.asyncio
async def test_expired_persistent_rows_are_deleted_and_refreshed(tmp_path):
    config = _config(tmp_path, "stale.db", ttl_seconds=60)
    fetch = AsyncMock()
    fetch.get_text.side_effect = [
        (
            "Y2_STATEFIPS,Y2_COUNTYFIPS,Y1_STATEFIPS,Y1_COUNTYFIPS,"
            "Y1_STATE,Y1_COUNTYNAME,N1,N2,AGI\n"
            "48,453,96,000,TX,Travis County Total Migration,100,220,5000\n"
        ),
        (
            "Y1_STATEFIPS,Y1_COUNTYFIPS,Y2_STATEFIPS,Y2_COUNTYFIPS,"
            "Y2_STATE,Y2_COUNTYNAME,N1,N2,AGI\n"
            "48,453,96,000,TX,Travis County Total Migration,80,175,4200\n"
        ),
    ]
    provider = IrsSoiProvider(
        config=config,
        fetch=fetch,
        db_path=config.cache_db_path,
    )
    provider._load_csv(
        "county_fips,year,inflow_returns,outflow_returns,inflow_exemptions,"
        "outflow_exemptions,inflow_agi,outflow_agi\n"
        "48453,2022-2023,1,0,999,0,1,0\n",
        None,
        None,
        True,
    )
    provider._mark_dataset_loaded()
    with provider._connect() as connection:
        connection.execute(
            "UPDATE soi_migration_meta SET loaded_at = datetime('now', '-2 minutes')"
        )

    metric = await provider.net_migration("48453")

    assert metric.value == 45
    assert fetch.get_text.await_count == 2
