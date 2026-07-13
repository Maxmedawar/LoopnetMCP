"""Listing-text and OpenStreetMap drive-thru/parking enrichment."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.enrichment.attributes import AttributeEnricher, parking_ratio
from cre_mcp.models import Listing

FIXTURES = Path(__file__).parents[1] / "fixtures" / "osm"


def _listing(**updates) -> Listing:
    values = {
        "source": "fixture",
        "source_id": "1",
        "name": "Retail Outparcel",
        "address": "7708 Burnet Rd",
        "city": "Austin",
        "state": "TX",
        "url": "https://example.test/1",
    }
    values.update(updates)
    return Listing(**values)


@pytest.mark.asyncio
async def test_drive_thru_listing_text_wins_without_osm():
    fetch = AsyncMock()
    listing = _listing(description="Signalized corner drive-thru opportunity")
    assert await AttributeEnricher(fetch).detect_drive_thru(listing) is True
    fetch.get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_drive_thru_and_parking_map_from_live_osm_fixture():
    fetch = AsyncMock()
    fetch.get_json.return_value = json.loads((FIXTURES / "attributes.json").read_text())
    listing = _listing(lat=30.3541, lon=-97.7326)
    enricher = AttributeEnricher(fetch)

    assert await enricher.detect_drive_thru(listing) is True
    assert await enricher.parking(listing) == "OpenStreetMap parking (surface)"
    assert "overpass-api.de/api/interpreter" in fetch.get_json.await_args.args[0]


@pytest.mark.asyncio
async def test_listing_parking_is_preferred_and_ratio_is_exposed():
    fetch = AsyncMock()
    listing = _listing(parking="80 Spaces (4.0/1,000 SF)", size_sqft_num=20_000)
    assert await AttributeEnricher(fetch).parking(listing) == listing.parking
    assert parking_ratio(listing.parking, listing.size_sqft_num) == 4.0
    assert parking_ratio("80 parking spaces", 20_000) == 4.0
    fetch.get_json.assert_not_awaited()
