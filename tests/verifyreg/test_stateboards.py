"""Offline Socrata normalizer and TREC-link tests."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from cre_mcp.verifyreg.stateboards import (
    StateBoardError,
    search_co_all_professions,
    search_co_real_estate,
    search_tx_tdlr,
    tx_trec_link_out,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "verifyreg"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_co_dora_captured_response_normalizes_and_uses_soql_name_filter():
    fetch = AsyncMock()
    fetch.get_json.return_value = load_json("co_dora_real_estate.json")

    candidates = await search_co_real_estate("Steven Du", client=fetch)

    assert candidates[0] == {
        "license_no": "100536270",
        "type": "Mortgage Loan Originator",
        "status": "Active",
        "expiry": "12/31/2026",
        "source": "CO DORA 4zse-6bnw",
        "name": "Steven Phan Du",
    }
    query = parse_qs(urlsplit(fetch.get_json.await_args.args[0]).query)
    assert "upper(firstname) like '%STEVEN%'" in query["$where"][0]
    assert "upper(lastname) like '%DU%'" in query["$where"][0]


@pytest.mark.asyncio
async def test_co_all_professions_uses_its_dataset_and_normalizer():
    fetch = AsyncMock()
    fetch.get_json.return_value = load_json("co_dora_real_estate.json")[:1]

    candidate = (await search_co_all_professions("Steven Du", client=fetch))[0]

    assert urlsplit(fetch.get_json.await_args.args[0]).path.endswith("/7s5z-vewr.json")
    assert candidate["source"] == "CO DORA 7s5z-vewr"


@pytest.mark.asyncio
async def test_tdlr_captured_response_normalizes_without_inventing_status():
    fetch = AsyncMock()
    fetch.get_json.return_value = load_json("tx_tdlr_all_licenses.json")

    candidates = await search_tx_tdlr("MEYER, JAMES", client=fetch)

    assert candidates[0] == {
        "license_no": "2935",
        "type": "A/C Technician",
        "status": None,
        "expiry": "06/02/2027",
        "source": "TX TDLR 7358-krk7",
        "name": "MEYER, JAMES",
    }
    where = parse_qs(urlsplit(fetch.get_json.await_args.args[0]).query)["$where"][0]
    assert "business_name" in where and "owner_name" in where


@pytest.mark.asyncio
async def test_state_board_license_filter_is_exact_soql():
    fetch = AsyncMock()
    fetch.get_json.return_value = []

    await search_tx_tdlr(license_no="2935", client=fetch)

    query = parse_qs(urlsplit(fetch.get_json.await_args.args[0]).query)
    assert query["$where"] == ["license_number='2935'"]
    assert query["$limit"] == ["25"]


@pytest.mark.asyncio
async def test_socrata_empty_list_is_no_match():
    fetch = AsyncMock()
    fetch.get_json.return_value = []

    assert await search_co_real_estate("Nobody", client=fetch) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"unexpected": "object"}, [{}], ["not-object"]])
async def test_socrata_schema_drift_fails_closed(payload):
    fetch = AsyncMock()
    fetch.get_json.return_value = payload

    with pytest.raises(StateBoardError, match="failed closed"):
        await search_tx_tdlr("Smith", client=fetch)


def test_trec_v1_is_lookup_and_flat_file_documentation_link_out():
    result = tx_trec_link_out()

    assert result["status"] == "not_queryable"
    assert result["deep_link"].endswith("/apps/license-holder-search/")
    assert result["documentation_url"].endswith("/public/high-value-data-sets")
    assert "flat" in result["note"].lower()
