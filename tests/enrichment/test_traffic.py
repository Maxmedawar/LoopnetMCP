"""Official state-DOT AADT selection and persistence."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.cache import SQLiteCache
from cre_mcp.config import CreConfig
from cre_mcp.enrichment.traffic import STATE_AADT_ENDPOINTS, TrafficProvider
from tests.conftest import write_cached_rights_registry

FIXTURES = Path(__file__).parents[1] / "fixtures" / "traffic"

_TRAFFIC_SOURCE_IDS = {
    "traffic.ncdot",
    "traffic.adot",
    "traffic.codot",
    "traffic.txdot",
    "traffic.fdot",
    "traffic.caltrans",
    "traffic.ndot",
    "traffic.gdot",
}


def _traffic_config(tmp_path) -> CreConfig:
    return CreConfig(
        _env_file=None,
        transport="stdio",
        cache_db_path=tmp_path / "traffic.db",
        source_rights_registry_path=write_cached_rights_registry(
            tmp_path,
            _TRAFFIC_SOURCE_IDS,
        ),
        source_rights_enabled={source_id: True for source_id in _TRAFFIC_SOURCE_IDS},
    )


@pytest.mark.asyncio
async def test_nearest_aadt_maps_closest_live_station_and_query_geometry(tmp_path):
    samples = json.loads((FIXTURES / "aadt_samples.json").read_text())["TX"]
    cache = SQLiteCache(tmp_path / "traffic.db")
    provider = TrafficProvider("tx", cache=cache, config=_traffic_config(tmp_path))
    with patch(
        "cre_mcp.enrichment.traffic.arcgis_query",
        new=AsyncMock(return_value=samples),
    ) as query:
        metric = await provider.nearest_aadt(30.2182, -97.6833, radius_m=250)

    assert metric is not None
    assert metric.value == 51053
    assert metric.unit == "vehicles/day"
    assert metric.as_of == "2025"
    assert "US0183" in metric.source
    assert query.await_args.kwargs["return_geometry"] is True
    assert query.await_args.kwargs["out_sr"] == 4326
    assert query.await_args.kwargs["geometry"]["spatialReference"] == {"wkid": 4326}


@pytest.mark.asyncio
async def test_nearest_aadt_second_instance_is_served_from_sqlite(tmp_path):
    samples = json.loads((FIXTURES / "aadt_samples.json").read_text())["NC"]
    cache_path = tmp_path / "traffic.db"
    first_query = AsyncMock(return_value=samples)
    config = _traffic_config(tmp_path)
    with patch("cre_mcp.enrichment.traffic.arcgis_query", new=first_query):
        first = await TrafficProvider(
            "NC", cache=SQLiteCache(cache_path), config=config
        ).nearest_aadt(35.84697, -78.58009)
    assert first is not None and first.value == 45500

    second_query = AsyncMock(side_effect=AssertionError("network should not run"))
    with patch("cre_mcp.enrichment.traffic.arcgis_query", new=second_query):
        second = await TrafficProvider(
            "NC", cache=SQLiteCache(cache_path), config=config
        ).nearest_aadt(35.84697, -78.58009)
    assert second == first
    second_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_each_shipped_state_schema_maps_and_unconfigured_state_skips(tmp_path):
    samples = json.loads((FIXTURES / "aadt_samples.json").read_text())
    assert set(STATE_AADT_ENDPOINTS) == {
        "NC",
        "AZ",
        "CO",
        "TX",
        "FL",
        "CA",
        "NV",
        "GA",
    }
    points = {
        "NC": (35.84697277, -78.58009081),
        "AZ": (33.4619, -112.1258),
        "CO": (39.6871, -104.9676),
        "TX": (30.218131, -97.683264),
        "FL": (28.52428, -81.3186),
        "CA": (34.02889815, -118.22646043),
        "NV": (36.24913014, -115.2465968),
        "GA": (33.62067, -84.36677),
    }
    config = _traffic_config(tmp_path)
    for state, (lat, lon) in points.items():
        with patch(
            "cre_mcp.enrichment.traffic.arcgis_query",
            new=AsyncMock(return_value=samples[state]),
        ):
            metric = await TrafficProvider(
                state,
                cache=SQLiteCache(tmp_path / f"{state}.db"),
                config=config,
            ).nearest_aadt(lat, lon)
        assert metric is not None and metric.value is not None

    with patch("cre_mcp.enrichment.traffic.arcgis_query", new=AsyncMock()) as query:
        assert await TrafficProvider(
            "WA", cache=SQLiteCache(tmp_path / "wa.db"), config=config
        ).nearest_aadt(47.6, -122.3) is None
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinate_field_layer_builds_bounded_where_without_geometry(tmp_path):
    samples = json.loads((FIXTURES / "aadt_samples.json").read_text())["GA"]
    with patch(
        "cre_mcp.enrichment.traffic.arcgis_query",
        new=AsyncMock(return_value=samples),
    ) as query:
        metric = await TrafficProvider(
            "GA",
            cache=SQLiteCache(tmp_path / "ga.db"),
            config=_traffic_config(tmp_path),
        ).nearest_aadt(33.62067, -84.36677)

    assert metric is not None and metric.value == 20_700
    assert query.await_args.kwargs["geometry"] is None
    assert query.await_args.kwargs["return_geometry"] is False
    assert "lat >=" in query.await_args.kwargs["where"]
    assert "lng <=" in query.await_args.kwargs["where"]
