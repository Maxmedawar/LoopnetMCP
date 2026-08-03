"""Socrata permit query and fixture-backed response tests."""

import json
from datetime import date
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.zoning.permits import build_permit_query, permits_near
from tests.conftest import load_fixture


@pytest.mark.parametrize(
    ("city", "dataset", "date_field", "location_field"),
    [
        ("Austin, TX", "3syk-w9eu", "issue_date", "location"),
        ("Chicago, IL", "ydr8-5enu", "issue_date", "location"),
        ("San Francisco, CA", "i98e-djp9", "issued_date", "location"),
        ("Los Angeles, CA", "pi9x-tg5x", "issue_date", "geolocation"),
        ("Seattle, WA", "76t5-zqzr", "issueddate", "location1"),
    ],
)
def test_permit_soql_builder_uses_city_schema_and_within_circle(
    city,
    dataset,
    date_field,
    location_field,
):
    source, url, since = build_permit_query(
        41.8781,
        -87.6298,
        city,
        365,
        today=date(2026, 7, 14),
    )
    params = parse_qs(urlparse(url).query)

    assert source.dataset_id == dataset
    assert since == "2025-07-14T00:00:00.000"
    assert params["$where"] == [
        f"{date_field} > '2025-07-14T00:00:00.000' AND "
        f"within_circle({location_field}, 41.8781, -87.6298, 500)"
    ]
    assert params["$limit"] == ["1000"]


@pytest.mark.asyncio
async def test_real_chicago_fixture_is_returned_with_source_and_optional_token():
    fetch = AsyncMock()
    fixture = json.loads(load_fixture("zoning/chicago_permits.json"))
    fetch.get_json.return_value = fixture
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        socrata_app_token="test-token",
        source_rights_enabled={"permits.chicago": True},
    )

    result = await permits_near(
        41.8781,
        -87.6298,
        "Chicago, IL",
        365,
        fetch=fetch,
        config=config,
    )

    assert result["status"] == "OK"
    assert result["count"] == 2
    assert result["permits"][0]["permit_id"] == "B200432852"
    assert result["permits"][0]["address"] == "145 S WELLS ST"
    assert "contact_1_name" not in result["permits"][0]
    assert result["source_endpoint"].endswith("/ydr8-5enu.json")
    assert result["source_layer"] == "Building Permits (ydr8-5enu)"
    assert result["app_token_used"] is True
    assert fetch.get_json.await_args.kwargs["headers"] == {
        "X-App-Token": "test-token"
    }


@pytest.mark.asyncio
async def test_unknown_source_native_permit_fields_cannot_reach_output():
    fetch = AsyncMock()
    fetch.get_json.return_value = [
        {
            "permit_": "B-1",
            "permit_type": "New Construction",
            "private_upstream_field": "must-not-survive",
            "contact_1_name": "must-not-survive",
        }
    ]
    config = CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={"permits.chicago": True},
    )

    result = await permits_near(
        41.8781,
        -87.6298,
        "Chicago, IL",
        365,
        fetch=fetch,
        config=config,
    )

    assert result["permits"] == [
        {"permit_id": "B-1", "permit_type": "New Construction"}
    ]


@pytest.mark.asyncio
async def test_unsupported_permit_city_returns_discovery_hint_without_http():
    fetch = AsyncMock()

    result = await permits_near(33.749, -84.388, "Atlanta, GA", 365, fetch=fetch)

    assert result["status"] == "UNSUPPORTED"
    assert "ArcGIS" in result["discovery_hint"]
    fetch.get_json.assert_not_awaited()
