"""Owner normalization, classification, absentee detection, and caching."""

import sqlite3
from unittest.mock import AsyncMock, Mock, patch

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.arcgis import ArcgisParcelProvider
from cre_mcp.enrichment.owner import (
    OwnerLookup,
    entity_type,
    is_absentee,
    normalize_owner_name,
)
from cre_mcp.models import GeoLevel, GeoRef, ParcelRecord
from tests.conftest import write_cached_rights_registry


def _geo() -> GeoRef:
    return GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="37",
        county_fips="37081",
        name="Guilford County, NC",
    )


def _parcel(**updates) -> ParcelRecord:
    values = {
        "apn": "123",
        "site_address": "100 Main St, Greensboro, NC 27401",
        "owner_name": "Example Holdings LLC",
        "owner_mailing_address": "500 Market St, Charlotte, NC 28202",
        "assessed_value": 1_000_000,
    }
    values.update(updates)
    return ParcelRecord(**values)


def test_name_normalization():
    assert normalize_owner_name("  Acme,  Holdings L.L.C. ") == "ACME HOLDINGS L L C"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Example Holdings LLC", "llc"),
        ("Jane Doe Revocable Trust", "trust"),
        ("Main Street Retail Inc", "corp"),
        ("Jane Q Doe", "individual"),
    ],
)
def test_entity_type_heuristic(name, expected):
    assert entity_type(name) == expected


def test_absentee_detection_compares_site_and_mailing_state_zip():
    assert is_absentee(_parcel()) is True
    assert (
        is_absentee(
            _parcel(owner_mailing_address="PO Box 20, Greensboro, NC 27401")
        )
        is False
    )
    assert is_absentee(_parcel(site_address="100 Main St")) is None


@pytest.mark.asyncio
async def test_owner_lookup_persists_result_and_second_instance_skips_provider(tmp_path):
    provider = Mock()
    provider.lookup = AsyncMock(return_value=_parcel())
    factory = Mock(return_value=provider)
    config = CreConfig(cache_db_path=tmp_path / "owner.db")
    first = OwnerLookup(
        config,
        cache=SQLiteCache(config.cache_db_path),
        resolver=AsyncMock(return_value=_geo()),
        provider_factory=factory,
    )
    owner = await first.lookup(address="100 Main St", county="Guilford County, NC")

    second_factory = Mock()
    second = OwnerLookup(
        config,
        cache=SQLiteCache(config.cache_db_path),
        resolver=AsyncMock(return_value=_geo()),
        provider_factory=second_factory,
    )
    cached = await second.lookup(address="100 Main St", county="Guilford County, NC")

    assert owner is not None and cached is not None
    assert owner.normalized_name == "EXAMPLE HOLDINGS LLC"
    assert owner.entity_type == "llc"
    assert owner.absentee is True
    assert cached == owner
    provider.lookup.assert_awaited_once()
    second_factory.assert_not_called()


@pytest.mark.asyncio
async def test_owner_lookup_gracefully_skips_unconfigured_county(tmp_path):
    lookup = OwnerLookup(
        CreConfig(cache_db_path=tmp_path / "owner.db"),
        resolver=AsyncMock(
            return_value=GeoRef(
                level=GeoLevel.COUNTY,
                state_fips="17",
                county_fips="17031",
                name="Cook County, IL",
            )
        ),
    )
    assert await lookup.lookup(address="100 State St, Chicago, IL") is None


@pytest.mark.asyncio
async def test_owner_lookup_prefers_free_county_record_even_when_paid_key_exists(tmp_path):
    free = Mock()
    free.lookup = AsyncMock(return_value=_parcel())
    paid_factory = Mock()
    lookup = OwnerLookup(
        CreConfig(
            regrid_api_key="explicit-fixture-key",
            cache_db_path=tmp_path / "owner.db",
            _env_file=None,
        ),
        resolver=AsyncMock(return_value=_geo()),
        provider_factory=Mock(return_value=free),
        paid_provider_factories=(paid_factory,),
    )

    owner = await lookup.lookup(address="100 Main St, Greensboro, NC")

    assert owner is not None and owner.name == "Example Holdings LLC"
    free.lookup.assert_awaited_once()
    paid_factory.assert_not_called()


@pytest.mark.asyncio
async def test_owner_lookup_uses_explicit_paid_fallback_only_after_free_miss(tmp_path):
    free = Mock()
    free.lookup = AsyncMock(return_value=None)
    paid = Mock()
    paid.lookup = AsyncMock(return_value=_parcel(owner_name="Paid Source LLC"))
    paid_factory = Mock(return_value=paid)
    lookup = OwnerLookup(
        CreConfig(
            regrid_api_key="explicit-fixture-key",
            cache_db_path=tmp_path / "owner.db",
            _env_file=None,
        ),
        resolver=AsyncMock(return_value=_geo()),
        provider_factory=Mock(return_value=free),
        paid_provider_factories=(paid_factory,),
    )

    owner = await lookup.lookup(address="100 Main St, Greensboro, NC")

    assert owner is not None and owner.name == "Paid Source LLC"
    free.lookup.assert_awaited_once()
    paid.lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_lookup_treats_missing_free_owner_name_as_weak_coverage(tmp_path):
    free = Mock()
    free.lookup = AsyncMock(return_value=_parcel(owner_name=None))
    paid = Mock()
    paid.lookup = AsyncMock(return_value=_parcel(owner_name="Complete Paid Owner LLC"))
    lookup = OwnerLookup(
        CreConfig(
            attom_api_key="explicit-fixture-key",
            cache_db_path=tmp_path / "owner.db",
            _env_file=None,
        ),
        resolver=AsyncMock(return_value=_geo()),
        provider_factory=Mock(return_value=free),
        paid_provider_factories=(Mock(return_value=paid),),
    )

    owner = await lookup.lookup(address="100 Main St, Greensboro, NC")

    assert owner is not None and owner.name == "Complete Paid Owner LLC"
    paid.lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_cache_separates_parcel_only_from_sales_enrichment(tmp_path):
    registry_path = write_cached_rights_registry(
        tmp_path,
        {"parcel.maricopa_04013", "sales.maricopa_04013"},
    )
    cache_path = tmp_path / "owner-rights.db"
    shared = {
        "_env_file": None,
        "transport": "stdio",
        "cache_db_path": cache_path,
        "source_rights_registry_path": registry_path,
    }
    with_sales = CreConfig(
        **shared,
        source_rights_enabled={
            "parcel.maricopa_04013": True,
            "sales.maricopa_04013": True,
        },
    )
    parcel_only = CreConfig(
        **shared,
        source_rights_enabled={"parcel.maricopa_04013": True},
    )
    geo = GeoRef(
        level=GeoLevel.COUNTY,
        state_fips="04",
        county_fips="04013",
        name="Maricopa County, AZ",
    )
    sale_parcel = _parcel(last_sale_price=850_000, last_sale_date="2025-01-10")
    plain_parcel = _parcel(last_sale_price=None, last_sale_date=None)

    first_fetch = AsyncMock(return_value=sale_parcel)
    with patch.object(ArcgisParcelProvider, "lookup", new=first_fetch):
        first = await OwnerLookup(with_sales).lookup(address="100 Main St", geo=geo)

    second_fetch = AsyncMock(return_value=plain_parcel)
    with patch.object(ArcgisParcelProvider, "lookup", new=second_fetch):
        second = await OwnerLookup(parcel_only).lookup(address="100 Main St", geo=geo)

    assert first is not None and first.parcels[0].last_sale_price == 850_000
    assert second is not None and second.parcels[0].last_sale_price is None
    first_fetch.assert_awaited_once()
    second_fetch.assert_awaited_once()
    with sqlite3.connect(cache_path) as connection:
        keys = [row[0] for row in connection.execute("SELECT key FROM cache")]
    assert any(":sales:" in key for key in keys)
    assert any(":parcel:" in key for key in keys)
