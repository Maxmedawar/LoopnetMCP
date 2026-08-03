"""Offline parsing and defensive-failure tests for BrokerCheck and IAPD."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from cre_mcp.http.errors import FetchClientError
from cre_mcp.verifyreg.finra import (
    RegistryAPIError,
    search_brokercheck_firms,
    search_brokercheck_individuals,
    search_iapd_firms,
    search_iapd_individuals,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "verifyreg"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_brokercheck_parses_captured_candidates_without_inventing_states():
    fetch = AsyncMock()
    fetch.get_json.return_value = load_json("brokercheck_individual_smith_ny.json")

    candidates = await search_brokercheck_individuals("John Smith", "ny", client=fetch)

    first = candidates[0]
    assert first == {
        "crd": "4539401",
        "name": "JOHN N SMITH",
        "firm": "MORGAN STANLEY",
        "exams": [],
        "states": [],
        "disclosure_count": 0,
        "bc_url": "https://brokercheck.finra.org/individual/summary/4539401",
        "disclosure_flag": "N",
    }
    assert candidates[1]["disclosure_count"] is None
    assert candidates[1]["disclosure_flag"] == "Y"
    query = parse_qs(urlsplit(fetch.get_json.await_args.args[0]).query)
    assert query["query"] == ["John Smith"]
    assert query["state"] == ["NY"]
    assert query["includePrevious"] == ["true"]
    assert query["nrows"] == ["12"]
    assert query["wt"] == ["json"]


@pytest.mark.asyncio
async def test_brokercheck_maps_optional_registry_fields_when_returned():
    fetch = AsyncMock()
    fetch.get_json.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "ind_source_id": "101",
                        "ind_firstname": "Ada",
                        "ind_lastname": "Lovelace",
                        "ind_current_employments": [{"firm_name": "Analytical LLC"}],
                        "ind_exams": ["S7", {"exam_name": "S63"}],
                        "ind_registered_states": ["NY", {"state_code": "CO"}],
                        "ind_bc_disclosure_count": "2",
                    }
                }
            ]
        }
    }

    candidate = (await search_brokercheck_individuals("Ada", client=fetch))[0]

    assert candidate["exams"] == ["S7", "S63"]
    assert candidate["states"] == ["NY", "CO"]
    assert candidate["disclosure_count"] == 2


@pytest.mark.asyncio
async def test_brokercheck_firm_shape_and_url():
    fetch = AsyncMock()
    fetch.get_json.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "firm_source_id": "149777",
                        "firm_name": "MORGAN STANLEY",
                        "firm_bc_disclosure_fl": "N",
                    }
                }
            ]
        }
    }

    candidate = (await search_brokercheck_firms("Morgan Stanley", client=fetch))[0]

    assert candidate["crd"] == "149777"
    assert candidate["name"] == candidate["firm"] == "MORGAN STANLEY"
    assert candidate["bc_url"].endswith("/firm/summary/149777")


@pytest.mark.asyncio
async def test_iapd_parses_captured_individual_candidate():
    fetch = AsyncMock()
    fetch.get_json.return_value = load_json("iapd_individual_smith_ny.json")

    candidates = await search_iapd_individuals("Smith", "NY", client=fetch)

    assert candidates[0] == {
        "crd": "6658650",
        "firm": "TRUIST SECURITIES, INC.",
        "iapd_url": "https://adviserinfo.sec.gov/individual/summary/6658650",
    }


@pytest.mark.asyncio
async def test_iapd_firm_shape_and_url():
    fetch = AsyncMock()
    fetch.get_json.return_value = {
        "hits": {
            "hits": [
                {"_source": {"firm_source_id": "801", "firm_name": "Example Advisers"}}
            ]
        }
    }

    candidate = (await search_iapd_firms("Example Advisers", client=fetch))[0]

    assert candidate == {
        "crd": "801",
        "firm": "Example Advisers",
        "iapd_url": "https://adviserinfo.sec.gov/firm/summary/801",
    }


@pytest.mark.asyncio
async def test_empty_hits_are_a_no_match_candidate_list():
    fetch = AsyncMock()
    fetch.get_json.return_value = {"hits": {"total": 0, "hits": []}}

    assert await search_brokercheck_individuals("Nobody", client=fetch) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("search", [search_brokercheck_individuals, search_iapd_individuals])
async def test_4xx_fetch_failure_is_closed_with_undocumented_api_note(search):
    fetch = AsyncMock()
    fetch.get_json.side_effect = FetchClientError("Unexpected status 404")

    with pytest.raises(RegistryAPIError, match="undocumented public JSON API"):
        await search("Smith", client=fetch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"hits": None},
        {"hits": {"hits": [{"changed": "shape"}]}},
        {"errorCode": -1, "errorMessage": "Exceeded limit", "hits": None},
    ],
)
async def test_brokercheck_schema_drift_fails_closed(payload):
    fetch = AsyncMock()
    fetch.get_json.return_value = payload

    with pytest.raises(RegistryAPIError, match="undocumented public JSON API"):
        await search_brokercheck_individuals("Smith", client=fetch)
