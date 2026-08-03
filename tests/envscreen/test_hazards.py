"""Offline proofs for NFHL, WHP, and USGS hazard parsing."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from cre_mcp.envscreen.hazards import (
    FLOOD_NULL_NOTE,
    fema_flood_zone,
    hazard_profile,
    parse_flood_payload,
    parse_whp_payload,
)
from cre_mcp.envscreen import tools

FIXTURES = Path(__file__).parents[1] / "fixtures" / "envscreen"
HOUSTON = (29.7355, -95.2654)


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


class OnePayloadFetch:
    def __init__(self, payload):
        self.payload = payload

    async def get_json(self, url: str):
        return self.payload


class HazardFixtureFetch:
    def __init__(self):
        self.urls: list[str] = []

    async def get_json(self, url: str):
        self.urls.append(url)
        if "NFHL/MapServer/28/query" in url:
            return fixture("nfhl_houston.json")
        if "WildfireHazardPotential" in url:
            return fixture("whp_suburban_low.json")
        if "designmaps/asce7-22.json" in url:
            return fixture("usgs_design_houston_reduced.json")
        if "fdsnws/event/1/query" in url:
            return fixture("usgs_quakes_houston.json")
        raise AssertionError(f"unexpected live URL: {url}")


def test_flood_zone_parse_normalizes_sfha_and_bfe_sentinel():
    zones = parse_flood_payload(fixture("nfhl_houston.json"))

    assert zones == [
        {
            "flood_zone": "X",
            "zone_subtype": "AREA OF MINIMAL FLOOD HAZARD",
            "special_flood_hazard_area": False,
            "static_bfe_ft": None,
            "source": "FEMA NFHL",
            "source_url": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
        }
    ]


@pytest.mark.asyncio
async def test_flood_unmapped_null_is_not_confused_with_query_failure():
    null = await fema_flood_zone(
        *HOUSTON, fetch=OnePayloadFetch(fixture("nfhl_unmapped.json"))
    )
    failed = await fema_flood_zone(
        *HOUSTON, fetch=OnePayloadFetch(fixture("nfhl_error.json"))
    )

    assert null["status"] == "null"
    assert null["zone"] is None
    assert null["note"] == FLOOD_NULL_NOTE
    assert failed["status"] == "query_failed"
    assert failed["zone"] is None
    assert "fixture service failure" in failed["error"]


def test_whp_point_sample_parses_landscape_class():
    hazard = parse_whp_payload(fixture("whp_suburban_low.json"))

    assert hazard["class_value"] == 2
    assert hazard["class_label"] == "low"
    assert hazard["resolution_m"] == 270
    assert hazard["parcel_specific"] is False


@pytest.mark.asyncio
async def test_hazard_profile_reports_every_source_status_and_ends_with_gaps():
    fetch = HazardFixtureFetch()
    report = await hazard_profile(*HOUSTON, fetch=fetch)

    assert report["results"]["flood"]["status"] == "hit"
    assert report["results"]["wildfire"]["hazard"]["class_label"] == "low"
    design = report["results"]["seismic_design"]["design_values"]
    assert design["SS"] == 0.082
    assert design["SD1"] == 0.065
    assert design["site_specific_geotech_required"] is True
    assert report["results"]["earthquake_catalog"]["status"] == "null"
    assert report["results"]["earthquake_catalog"]["count"] == 0
    assert report["sources_failed"] == []
    assert next(reversed(report)) == "uncoverable_gaps"


def test_tools_are_plain_async_functions_not_registered_objects():
    assert inspect.iscoroutinefunction(tools.environmental_screen)
    assert inspect.iscoroutinefunction(tools.flood_zone)
    assert inspect.iscoroutinefunction(tools.hazard_profile)
    assert not hasattr(tools.environmental_screen, "tool")
