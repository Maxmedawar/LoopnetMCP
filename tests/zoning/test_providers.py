"""Provider registry, query-builder, and captured normalization tests."""

import json
from urllib.parse import parse_qs, urlparse

from cre_mcp.zoning.providers import (
    PROVIDERS,
    build_arcgis_query,
    build_socrata_zoning_query,
    normalize_base_payload,
    resolve_provider,
)
from tests.conftest import load_fixture


def _fixture(name: str):
    return json.loads(load_fixture(f"zoning/{name}"))


def test_registry_wires_every_documented_zoning_jurisdiction():
    assert {
        "austin",
        "phoenix",
        "denver",
        "dallas",
        "atlanta",
        "las_vegas_city",
        "clark_county",
        "new_york_city",
        "san_francisco",
        "seattle",
        "houston",
    } <= PROVIDERS.keys()
    assert resolve_provider("Las Vegas Strip").key == "clark_county"
    assert resolve_provider("City of Las Vegas, NV").key == "las_vegas_city"


def test_phoenix_arcgis_query_marks_wgs84_input_for_native_sr_2868():
    url = build_arcgis_query(PROVIDERS["phoenix"], 33.4484, -112.074)
    params = parse_qs(urlparse(url).query)

    assert params["inSR"] == ["4326"]
    assert params["outSR"] == ["4326"]
    assert params["geometryType"] == ["esriGeometryPoint"]
    assert params["spatialRel"] == ["esriSpatialRelIntersects"]
    assert params["returnGeometry"] == ["true"]
    assert json.loads(params["geometry"][0]) == {
        "x": -112.074,
        "y": 33.4484,
        "spatialReference": {"wkid": 4326},
    }


def test_nyc_socrata_builder_uses_polygon_intersection():
    url = build_socrata_zoning_query(
        PROVIDERS["new_york_city"],
        40.7128,
        -74.006,
    )
    params = parse_qs(urlparse(url).query)

    assert params["$where"] == [
        "intersects(geom, 'POINT (-74.006 40.7128)')"
    ]
    assert params["$limit"] == ["10"]


def test_austin_real_fixture_normalizes_base_district_and_citation():
    rows = normalize_base_payload(
        PROVIDERS["austin"],
        _fixture("austin_zoning.json"),
    )

    assert rows == [
        {
            "district": "GR-V",
            "description": None,
            "ordinance": None,
            "effective_date": None,
            "source_endpoint": PROVIDERS["austin"].base_layer.endpoint,
            "source_layer": "0 — Zoning",
            "inline_overlays": [],
        }
    ]


def test_atlanta_real_fixture_maps_zoneclass_and_effective_field():
    row = normalize_base_payload(
        PROVIDERS["atlanta"],
        _fixture("atlanta_zoning.json"),
    )[0]

    assert row["district"] == "SPI-1 SA1"
    assert row["description"].startswith("https://library.municode.com/")
    assert row["effective_date"] == "1900-01-01T00:00:00Z"
    assert row["ordinance"] is None
    assert row["source_layer"] == "0 — Zoning District"


def test_clark_county_real_fixture_maps_strip_to_county_zone():
    row = normalize_base_payload(
        PROVIDERS["clark_county"],
        _fixture("clark_county_zoning.json"),
    )[0]

    assert row["district"] == "CR"
    assert row["description"] == "Commercial Resort"
    assert row["source_layer"] == "11 — Clark County Zoning"
