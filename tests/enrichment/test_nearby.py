"""Nearby-brand parsing, classification, summaries, and failure behavior."""

from unittest.mock import Mock, patch

import pytest

from cre_mcp.enrichment import nearby
from cre_mcp.enrichment.nearby import (
    _haversine_m,
    classify_anchor,
    nearby_brands,
    trade_area_anchors,
)

SUBJECT_LAT = 30.2672
SUBJECT_LON = -97.7431
OVERPASS_SAMPLE = {
    "elements": [
        {
            "type": "node",
            "id": 101,
            "lat": 30.2682,
            "lon": -97.7431,
            "tags": {"brand": "Starbucks", "amenity": "cafe"},
        },
        {
            "type": "way",
            "id": 202,
            "center": {"lat": 30.2692, "lon": -97.7431},
            "tags": {"brand": "Whole Foods Market", "shop": "supermarket"},
        },
        {
            "type": "node",
            "id": 303,
            "lat": 30.2672,
            "lon": -97.7426,
            "tags": {
                "brand": "Chipotle",
                "amenity": "fast_food",
                "cuisine": "mexican",
            },
        },
    ]
}


@pytest.fixture(autouse=True)
def _clear_nearby_cache():
    with nearby._CACHE_LOCK:
        nearby._CACHE.clear()
    yield
    with nearby._CACHE_LOCK:
        nearby._CACHE.clear()


def _response(payload: dict = OVERPASS_SAMPLE, status_code: int = 200) -> Mock:
    response = Mock(status_code=status_code)
    response.json.return_value = payload
    return response


def test_nearby_brands_parses_nodes_way_centers_categories_and_distances():
    with patch(
        "cre_mcp.enrichment.nearby.requests.post",
        return_value=_response(),
    ) as post:
        results = nearby_brands(SUBJECT_LAT, SUBJECT_LON, radius_m=400)

    assert [result["brand"] for result in results] == [
        "Chipotle",
        "Starbucks",
        "Whole Foods Market",
    ]
    assert all(isinstance(result["distance_m"], int) for result in results)
    assert 30 < results[0]["distance_m"] < 70
    assert results[1]["category"] == "cafe"
    assert results[2]["category"] == "supermarket"
    assert results[2]["lat"] == pytest.approx(30.2692)
    assert results[2]["osm_id"] == 202
    assert post.call_args.kwargs["headers"]["User-Agent"] == (
        "MedawarCRE/1.0 (max@efreedom.com)"
    )
    assert "nwr(around:400" in post.call_args.kwargs["data"]["data"]


def test_haversine_distance_is_sane():
    distance = _haversine_m(30.0, -97.0, 30.001, -97.0)
    assert 110 < distance < 112


def test_classify_anchor_handles_complementary_competitor_and_big_box():
    assert classify_anchor({"brand": "Starbucks", "category": "cafe"}) == (
        "complementary_anchor"
    )
    assert classify_anchor(
        {"brand": "Local Books", "category": "books"},
        subject_category="books",
    ) == "competitor"
    assert classify_anchor({"brand": "Target", "category": "general"}) == (
        "complementary_anchor"
    )
    assert classify_anchor({"brand": "Local Books", "category": "books"}) == "neutral"


def test_trade_area_anchors_lists_brand_names_in_summary():
    with patch(
        "cre_mcp.enrichment.nearby.requests.post",
        return_value=_response(),
    ):
        result = trade_area_anchors(
            SUBJECT_LAT,
            SUBJECT_LON,
            radius_m=400,
            subject_category="supermarket",
        )

    assert result["anchor_count"] == 2
    assert [item["brand"] for item in result["competitors"]] == [
        "Whole Foods Market"
    ]
    assert result["brands"] == ["Chipotle", "Starbucks", "Whole Foods Market"]
    assert result["summary"] == "Chipotle, Starbucks, Whole Foods Market within 400m"


def test_nearby_brands_returns_empty_after_all_mirrors_fail():
    with patch(
        "cre_mcp.enrichment.nearby.requests.post",
        side_effect=RuntimeError("network unavailable"),
    ) as post:
        assert nearby_brands(SUBJECT_LAT, SUBJECT_LON) == []

    assert post.call_count == 3


@pytest.mark.asyncio
async def test_tool_wrappers_return_dicts_and_capture_errors():
    from cre_mcp.tools import nearby_tools

    with patch.object(nearby_tools, "_nearby_brands", return_value=[{"brand": "Chase"}]):
        result = await nearby_tools.nearby_brands(SUBJECT_LAT, SUBJECT_LON)
    assert result == {
        "brands": [{"brand": "Chase"}],
        "count": 1,
        "radius_m": 800,
    }

    with patch.object(
        nearby_tools,
        "_trade_area_anchors",
        side_effect=RuntimeError("offline"),
    ):
        assert await nearby_tools.trade_area_anchors(SUBJECT_LAT, SUBJECT_LON) == {
            "error": "offline"
        }
