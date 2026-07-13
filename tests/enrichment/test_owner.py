"""Owner normalization, classification, absentee detection, and caching."""

from unittest.mock import AsyncMock, Mock

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.owner import (
    OwnerLookup,
    entity_type,
    is_absentee,
    normalize_owner_name,
)
from cre_mcp.models import GeoLevel, GeoRef, ParcelRecord


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
                state_fips="48",
                county_fips="48453",
                name="Travis County, TX",
            )
        ),
    )
    assert await lookup.lookup(address="100 Congress Ave, Austin, TX") is None
