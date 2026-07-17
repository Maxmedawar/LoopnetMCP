"""Structure and exchange MCP boundary tests."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.server import mcp
from cre_mcp.tools.structure_tools import (
    calc_boot_basis,
    exchange_status,
    identify_replacement,
    recommend_structure,
    start_exchange,
)
from tests.scoring.builders import deal_context
from tests.expected import EXPECTED_TOOL_COUNT


async def _save(store: DealStore, source_id: str, price: float):
    deal_id = await store.save_deal(deal_context(source_id=source_id, price=price).listing)
    assert deal_id is not None
    return deal_id


@pytest.mark.asyncio
async def test_recommend_structure_tool_surfaces_partnership_and_sec_gates():
    result = await recommend_structure("syndication", investors=5, state="TX")
    text = " ".join([*result["traps"], result["counsel_gate"]])

    assert result["recommended"] == "LLC"
    assert "1031-INELIGIBLE" in text
    assert "SEC GATE" in text
    assert "securities attorney" in text


@pytest.mark.asyncio
async def test_exchange_tools_start_identify_and_report_status(tmp_path):
    store = DealStore(tmp_path / "exchange.db")
    relinquished = await _save(store, "rel", 1_000_000)
    replacement = await _save(store, "replacement", 1_100_000)
    close = date.today().isoformat()
    with patch("cre_mcp.tools.structure_tools.get_deal_store", return_value=store):
        started = await start_exchange(relinquished, close)
        identified = await identify_replacement(started["exchange_id"], replacement)
        status = await exchange_status(started["exchange_id"])

    assert started["days_to_identification_deadline"] == 45
    assert started["days_to_exchange_deadline"] == 180
    assert "Qualified Intermediary BEFORE" in started["qi_gate"]
    assert identified["replacements"][0]["deal_id"] == replacement
    assert status["replacements"] == identified["replacements"]


@pytest.mark.asyncio
async def test_start_and_identify_can_analyze_unsaved_source_ids(tmp_path):
    store = DealStore(tmp_path / "exchange.db")
    listings = {
        "raw-rel": deal_context(source_id="raw-rel", price=1_000_000).listing,
        "raw-rep": deal_context(source_id="raw-rep", price=1_200_000).listing,
    }

    async def analyze(value, source="loopnet"):
        return {"listing": listings[value].model_dump(mode="json"), "scores": []}

    with (
        patch("cre_mcp.tools.structure_tools.get_deal_store", return_value=store),
        patch(
            "cre_mcp.tools.structure_tools.analyze_deal",
            new=AsyncMock(side_effect=analyze),
        ) as mocked,
    ):
        started = await start_exchange("raw-rel", date.today().isoformat(), source="fixture")
        result = await identify_replacement(
            started["exchange_id"],
            "raw-rep",
            source="fixture",
        )

    assert len(result["replacements"]) == 1
    assert mocked.await_count == 2


@pytest.mark.asyncio
async def test_boot_tool_and_error_paths_return_dicts(tmp_path):
    result = await calc_boot_basis(
        relinquished_price=1_000_000,
        relinquished_adjusted_basis=400_000,
        replacement_price=800_000,
        relinquished_debt=400_000,
        replacement_debt=300_000,
    )
    assert result["estimated_boot"] == 200_000
    assert result["taxable_boot_flag"] is True

    assert "error" in await recommend_structure("bad-mode")
    assert "error" in await calc_boot_basis(-1, 0, 1)
    store = DealStore(tmp_path / "errors.db")
    with patch("cre_mcp.tools.structure_tools.get_deal_store", return_value=store):
        assert await exchange_status(999) == {"error": "unknown exchange_id: 999"}


@pytest.mark.asyncio
async def test_structure_tools_registered_and_total_is_seventy_four():
    tools = await mcp.get_tools()
    assert {
        "recommend_structure",
        "start_exchange",
        "exchange_status",
        "identify_replacement",
        "calc_boot_basis",
    } <= set(tools)
    assert len(tools) == EXPECTED_TOOL_COUNT
