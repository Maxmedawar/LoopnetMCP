"""Listing-text and OpenStreetMap drive-thru/parking enrichment."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cre_mcp.enrichment.attributes import (
    OVERPASS_FALLBACK_URL,
    OVERPASS_HEADERS,
    OVERPASS_URL,
    AttributeEnricher,
    parking_ratio,
)
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
    fetch.post_form_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_drive_thru_and_parking_map_from_live_osm_fixture():
    fetch = AsyncMock()
    fetch.post_form_json.return_value = json.loads(
        (FIXTURES / "attributes.json").read_text()
    )
    listing = _listing(lat=30.3541, lon=-97.7326)
    enricher = AttributeEnricher(fetch)

    assert await enricher.detect_drive_thru(listing) is True
    assert await enricher.parking(listing) == "OpenStreetMap parking (surface)"
    url, body = fetch.post_form_json.await_args.args
    assert url == OVERPASS_URL
    assert body["data"].startswith("[out:json]")
    assert fetch.post_form_json.await_args.kwargs["headers"] == OVERPASS_HEADERS
    assert OVERPASS_HEADERS["Content-Type"] == "application/x-www-form-urlencoded"
    assert OVERPASS_HEADERS["User-Agent"].startswith("cre-mcp/")


@pytest.mark.asyncio
async def test_overpass_failure_falls_back_to_kumi_with_same_form_request():
    payload = json.loads((FIXTURES / "attributes.json").read_text())
    fetch = AsyncMock()
    fetch.post_form_json.side_effect = [RuntimeError("primary busy"), payload]

    assert await AttributeEnricher(fetch).detect_drive_thru(
        _listing(lat=30.3541, lon=-97.7326)
    ) is True
    assert [call.args[0] for call in fetch.post_form_json.await_args_list] == [
        OVERPASS_URL,
        OVERPASS_FALLBACK_URL,
    ]


@pytest.mark.asyncio
async def test_listing_parking_is_preferred_and_ratio_is_exposed():
    fetch = AsyncMock()
    listing = _listing(parking="80 Spaces (4.0/1,000 SF)", size_sqft_num=20_000)
    assert await AttributeEnricher(fetch).parking(listing) == listing.parking
    assert parking_ratio(listing.parking, listing.size_sqft_num) == 4.0
    assert parking_ratio("80 parking spaces", 20_000) == 4.0
    fetch.post_form_json.assert_not_awaited()
