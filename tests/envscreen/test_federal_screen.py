"""Offline proofs for EPA normalization and the honest screen contract."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from cre_mcp.envscreen.federal import (
    echo_radius,
    frs_radius,
    normalize_echo_payload,
    normalize_frs_payload,
)
from cre_mcp.envscreen.screen import (
    UNCOVERABLE_GAPS,
    dedupe_hits,
    environmental_screen,
    rec_candidate,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "envscreen"
HOUSTON = (29.7355, -95.2654)


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


class ScreenFixtureFetch:
    """Route generated URLs to local captures; an unknown URL fails the test."""

    def __init__(self):
        self.urls: list[str] = []

    async def get_json(self, url: str):
        self.urls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "frs_rest_services.get_facilities" in parsed.path:
            if query.get("pgm_sys_acrnm") == ["RCRAINFO"]:
                return fixture("frs_houston_rcra_excerpt.json")
            return fixture("frs_clean_rcra.json")
        if "echo_rest_services.get_facilities" in parsed.path:
            return fixture("echo_houston_search.json")
        if "echo_rest_services.get_qid" in parsed.path:
            if query.get("pageno") == ["1"]:
                return fixture("echo_houston_qid_excerpt.json")
            return fixture("echo_empty_page.json")
        raise AssertionError(f"unexpected live URL: {url}")


class EmptyFetch:
    async def get_json(self, url: str):
        return fixture("frs_clean_rcra.json")


class FailedFetch:
    async def get_json(self, url: str):
        raise RuntimeError("offline fixture failure")


def test_frs_normalization_cites_program_distance_registry_and_source():
    hits = normalize_frs_payload(
        fixture("frs_houston_rcra_excerpt.json"),
        lat=HOUSTON[0],
        lon=HOUSTON[1],
        program="RCRAINFO",
    )

    chevron = next(hit for hit in hits if hit["registry_id"] == "110008164244")
    assert chevron["name"] == "CHEVRON USA INC"
    assert chevron["program"] == "RCRAINFO"
    assert 0 < chevron["distance_mi"] < 0.25
    assert chevron["source"] == "EPA FRS REST"
    assert chevron["flags"]["corrective_action"] is None


def test_frs_dry_cleaner_flag_only_when_naics_is_returned():
    payload = {
        "Results": {
            "FRSFacility": [
                {
                    "RegistryId": "dry-1",
                    "FacilityName": "CURRENT CLEANER",
                    "Latitude83": "29.7355",
                    "Longitude83": "-95.2654",
                    "NAICSCodes": "812320 999999",
                }
            ]
        }
    }
    hit = normalize_frs_payload(
        payload, lat=HOUSTON[0], lon=HOUSTON[1], program="RCRAINFO"
    )[0]

    assert hit["flags"]["naics_codes"] == ["812320", "999999"]
    assert hit["flags"]["dry_cleaner_naics"] is True


@pytest.mark.asyncio
async def test_echo_radius_follows_qid_and_normalizes_compliance_flags():
    fetch = ScreenFixtureFetch()
    result = await echo_radius(*HOUSTON, 0.25, fetch=fetch)

    assert result["status"] == "hit"
    assert len(result["hits"]) == 2
    oneal = next(hit for hit in result["hits"] if hit["name"] == "O'NEAL STEEL INC")
    assert oneal["program"] == "ECHO"
    assert oneal["flags"]["programs"] == ["NPDES", "RCRAINFO"]
    assert oneal["flags"]["quarters_noncompliance"] == 9
    assert oneal["flags"]["distance_is_upper_bound"] is True
    assert oneal["distance_mi"] == 0.25
    search_url = next(url for url in fetch.urls if "get_facilities" in url)
    assert "p_sr=0.25" in search_url
    assert "p_radius=0.25" in search_url


@pytest.mark.asyncio
async def test_frs_null_and_query_failed_are_distinct_and_radius_is_capped():
    null = await frs_radius(*HOUSTON, 0.25, "RCRAINFO", fetch=EmptyFetch())
    failed = await frs_radius(*HOUSTON, 0.25, "RCRAINFO", fetch=FailedFetch())

    assert null["status"] == "null"
    assert null["hits"] == []
    assert null["error"] is None
    assert failed["status"] == "query_failed"
    assert failed["hits"] == []
    assert "offline fixture failure" in failed["error"]
    with pytest.raises(ValueError, match="at most 5"):
        await frs_radius(*HOUSTON, 5.1, "SEMS", fetch=EmptyFetch())


def test_dedupe_registry_id_keeps_minimum_distance_and_merges_sources():
    hits = [
        {
            "name": "A",
            "program": "RCRAINFO",
            "distance_mi": 0.42,
            "registry_id": "1",
            "flags": {"corrective_action": True},
            "source": "EPA FRS REST",
            "source_url": "frs",
        },
        {
            "name": "A ECHO",
            "program": "ECHO",
            "distance_mi": 0.2,
            "registry_id": "1",
            "flags": {"programs": ["RCRAINFO"], "current_violation": True},
            "source": "EPA ECHO",
            "source_url": "echo",
        },
    ]

    merged = dedupe_hits(hits)

    assert len(merged) == 1
    assert merged[0]["distance_mi"] == 0.2
    assert merged[0]["flags"]["corrective_action"] is True
    assert merged[0]["flags"]["current_violation"] is True
    assert {citation["source"] for citation in merged[0]["source_citations"]} == {
        "EPA FRS REST",
        "EPA ECHO",
    }


def test_sems_and_rcra_corrective_action_adjacent_are_high_conventions():
    sems_hit = normalize_frs_payload(
        fixture("frs_san_jacinto_sems.json"),
        lat=29.797,
        lon=-95.066,
        program="SEMS",
    )[0]
    sems_candidate = rec_candidate(dedupe_hits([sems_hit])[0])
    rcra_candidate = rec_candidate(
        dedupe_hits(
            [
                {
                    "name": "RCRA CA",
                    "program": "RCRAINFO",
                    "distance_mi": 0.5,
                    "registry_id": "rcra-ca",
                    "flags": {"corrective_action": True},
                    "source": "EPA FRS REST",
                }
            ]
        )[0]
    )

    assert sems_candidate["proximity"] == "ADJACENT"
    assert sems_candidate["severity"] == "high"
    assert rcra_candidate["severity"] == "high"
    assert rcra_candidate["severity_is_screening_convention"] is True


def test_tri_and_npdes_presence_are_context_not_contamination_findings():
    candidate = rec_candidate(
        dedupe_hits(
            [
                {
                    "name": "PERMITTED DISCHARGER",
                    "program": "NPDES",
                    "distance_mi": 0.1,
                    "registry_id": "npdes-1",
                    "flags": {},
                    "source": "EPA FRS REST",
                }
            ]
        )[0]
    )

    assert candidate["severity"] == "context"
    assert "not proof" in candidate["severity_basis"]


@pytest.mark.asyncio
async def test_environmental_screen_is_offline_deduped_and_always_ends_with_gaps():
    report = await environmental_screen(*HOUSTON, fetch=ScreenFixtureFetch())

    assert report["report_type"] == "PRE-PHASE-I ENVIRONMENTAL SCREEN"
    assert report["phase_i_substitute"] is False
    assert len(report["pipeline"]) == 7
    assert len(report["source_register"]) == 22
    assert len(report["sources_queried"]) == 18
    assert report["sources_failed"] == []
    assert all(
        result["status"] in {"hit", "null", "query_failed"}
        for result in report["source_results"]
    )
    registry_ids = [hit["registry_id"] for hit in report["federal_hits"]]
    assert len(registry_ids) == len(set(registry_ids)) == 3
    assert next(reversed(report)) == "uncoverable_gaps"
    assert report["uncoverable_gaps"] == UNCOVERABLE_GAPS
    assert {
        "site_reconnaissance",
        "historical_use",
        "interviews",
        "regulatory_file_review",
        "plume_and_vapor_reasoning",
    } <= report["uncoverable_gaps"].keys()
