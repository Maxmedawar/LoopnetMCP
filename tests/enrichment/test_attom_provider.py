"""ATTOM mapping, opt-in gating, and persistent paid-call caching."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.base import ProviderUnavailable
from cre_mcp.enrichment.providers.attom import (
    AttomProvider,
    map_attom_avm,
    map_attom_comp,
    map_attom_parcel,
)
from cre_mcp.models import GeoLevel, GeoRef, Listing
from tests.conftest import write_cached_rights_registry

FIXTURES = Path(__file__).parents[1] / "fixtures" / "attom"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


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
        zip_code="78701",
        property_type="retail",
        size_sqft_num=12_500,
        url="https://example.test/subject",
    )


def test_representative_attom_payloads_map_parcel_comps_and_avm():
    parcel = map_attom_parcel(_load("detail_owner.json")["property"][0])
    comp = map_attom_comp(
        _load("sales_comparables.json")["property"][0],
        "48453",
    )
    avm = map_attom_avm(_load("avm.json"))

    assert parcel.apn == "0123456789"
    assert parcel.owner_name == "MAIN STREET HOLDINGS LLC"
    assert parcel.assessed_value == 2_450_000
    assert parcel.building_sqft == 12_500
    assert parcel.last_sale_price == 2_100_000
    assert comp is not None and comp.sale_price == 2_350_000
    assert comp.source.startswith("ATTOM paid")
    assert avm is not None and avm.method == "attom"
    assert avm.mid == 2_400_000
    assert avm.confidence == 0.82
    assert avm.error_band == 0.10


@pytest.mark.asyncio
async def test_attom_without_key_fails_closed_before_network(tmp_path):
    fetch = AsyncMock()
    provider = AttomProvider(
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
async def test_attom_paid_results_are_persisted_and_second_instance_skips_network(
    tmp_path,
):
    config = CreConfig(
        attom_api_key="fixture-key",
        cache_db_path=tmp_path / "paid.db",
        source_rights_registry_path=write_cached_rights_registry(
            tmp_path,
            {"commercial.attom"},
        ),
        source_rights_enabled={"commercial.attom": True},
        _env_file=None,
    )
    first_fetch = AsyncMock()
    first_fetch.get_json.side_effect = [
        _load("sales_comparables.json"),
        _load("avm.json"),
    ]
    first = AttomProvider(config, fetch=first_fetch, cache=SQLiteCache(config.cache_db_path))

    result = await first.get_comps(_listing(), _geo())

    second_fetch = AsyncMock()
    second = AttomProvider(
        config,
        fetch=second_fetch,
        cache=SQLiteCache(config.cache_db_path),
    )
    cached = await second.get_comps(_listing(), _geo())

    assert len(result.comps) == 3
    assert result.value_estimate is not None
    assert result.value_estimate.method == "attom"
    assert cached == result
    assert first_fetch.get_json.await_count == 2
    assert first_fetch.get_json.await_args_list[0].kwargs["headers"]["apikey"] == "fixture-key"
    second_fetch.get_json.assert_not_awaited()
