"""Regrid mapping, opt-in gating, and paid parcel caching."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.base import ProviderUnavailable
from cre_mcp.enrichment.providers.regrid import RegridProvider, map_regrid_parcel
from cre_mcp.models import GeoLevel, GeoRef, Listing
from tests.conftest import write_cached_rights_registry

FIXTURES = Path(__file__).parents[1] / "fixtures" / "regrid"


def _payload():
    return json.loads((FIXTURES / "parcel.json").read_text())


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="48",
        county_fips="48453",
        name="Travis County, TX",
    )


def _listing() -> Listing:
    return Listing(
        source="fixture",
        source_id="subject",
        name="Retail subject",
        address="100 Main St, Austin, TX 78701",
        city="Austin",
        state="TX",
        property_type="retail",
        url="https://example.test/subject",
    )


def test_representative_regrid_geojson_maps_owner_and_parcel_fields():
    parcel = map_regrid_parcel(_payload()["parcels"]["features"][0])

    assert parcel.apn == "0123456789"
    assert parcel.site_address == "100 MAIN ST, AUSTIN TX 78701"
    assert parcel.owner_name == "MAIN STREET HOLDINGS LLC"
    assert parcel.owner_mailing_address == "PO BOX 100, DALLAS TX 75201"
    assert parcel.assessed_value == 2_450_000
    assert parcel.last_sale_price == 2_100_000
    assert parcel.building_sqft == 12_500


@pytest.mark.asyncio
async def test_regrid_without_key_fails_closed_before_network(tmp_path):
    fetch = AsyncMock()
    provider = RegridProvider(
        CreConfig(
            attom_api_key=None,
            regrid_api_key=None,
            cache_db_path=tmp_path / "paid.db",
            _env_file=None,
        ),
        fetch=fetch,
    )

    with pytest.raises(ProviderUnavailable, match="paid calls are off"):
        await provider.lookup("100 Main St, Austin, TX", None, _geo())

    fetch.get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_regrid_paid_result_is_cached_and_value_anchor_is_honestly_labeled(
    tmp_path,
):
    config = CreConfig(
        regrid_api_key="fixture-token",
        cache_db_path=tmp_path / "paid.db",
        source_rights_registry_path=write_cached_rights_registry(
            tmp_path,
            {"commercial.regrid"},
        ),
        source_rights_enabled={"commercial.regrid": True},
        _env_file=None,
    )
    first_fetch = AsyncMock()
    first_fetch.get_json.return_value = _payload()
    first = RegridProvider(config, fetch=first_fetch, cache=SQLiteCache(config.cache_db_path))

    result = await first.get_comps(_listing(), _geo())

    second_fetch = AsyncMock()
    second = RegridProvider(
        config,
        fetch=second_fetch,
        cache=SQLiteCache(config.cache_db_path),
    )
    parcel = await second.lookup(_listing().address, None, _geo())

    assert result.value_estimate is not None
    assert result.value_estimate.method == "regrid"
    assert result.value_estimate.confidence == 0.30
    assert "not closed-sale comps" in result.value_estimate.source
    assert parcel is not None and parcel.owner_name == "MAIN STREET HOLDINGS LLC"
    first_fetch.get_json.assert_awaited_once()
    assert "token=fixture-token" in first_fetch.get_json.await_args.args[0]
    second_fetch.get_json.assert_not_awaited()
