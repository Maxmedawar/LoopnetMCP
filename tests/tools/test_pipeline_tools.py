"""Pipeline and saved-search MCP boundary tests."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.server import mcp
from cre_mcp.tools.pipeline_tools import (
    ALERT_HOSTING_NOTE,
    add_to_pipeline,
    list_pipeline,
    list_searches,
    save_search,
    update_deal_stage,
)
from tests.scoring.builders import deal_context


def _analyzed() -> dict:
    ctx = deal_context(source_id="crm-1")
    return {
        "listing": ctx.listing.model_dump(mode="json"),
        "scores": [
            {"strategy": "nnn_retail", "score": 78.5, "grade": "B"}
        ],
        "best_strategy": "nnn_retail",
    }


@pytest.mark.asyncio
async def test_pipeline_tools_add_update_filter_and_dedupe(tmp_path):
    store = DealStore(tmp_path / "pipeline.db")
    with (
        patch("cre_mcp.tools.pipeline_tools.get_deal_store", return_value=store),
        patch(
            "cre_mcp.tools.pipeline_tools.analyze_deal",
            new=AsyncMock(return_value=_analyzed()),
        ),
    ):
        added = await add_to_pipeline(
            "crm-1",
            source="fixture",
            stage="lead",
            note="Worth a first call",
        )
        duplicate = await add_to_pipeline("crm-1", source="fixture", stage="analyzing")
        moved = await update_deal_stage(
            added["deal_id"],
            "contacted",
            "Broker called",
        )
        listed = await list_pipeline("contacted")

    assert added["score"] == 78.5
    assert duplicate["deal_id"] == added["deal_id"]
    assert moved["stage"] == "contacted"
    assert moved["last_note"]["text"] == "Broker called"
    assert listed["count"] == 1
    assert listed["by_stage"]["contacted"][0]["deal_id"] == added["deal_id"]
    assert len(await store.list_pipeline()) == 1


@pytest.mark.asyncio
async def test_saved_search_tools_validate_persist_and_disclose_pull_mode(tmp_path):
    store = DealStore(tmp_path / "pipeline.db")
    with patch("cre_mcp.tools.pipeline_tools.get_deal_store", return_value=store):
        saved = await save_search(
            "Austin buy box",
            "Austin, TX",
            strategy="nnn_retail",
            property_type="retail",
            price_min=1_000_000,
            price_max=4_000_000,
            min_score=75,
            sources=["crexi", "loopnet"],
        )
        searches = await list_searches()
        invalid = await save_search("Bad", "Austin", price_min=5, price_max=1)

    assert saved["search_id"] == 1
    assert saved["query"]["sources"] == ["crexi", "loopnet"]
    assert searches["count"] == 1
    assert searches["searches"][0]["min_score"] == 75
    assert searches["hosting_note"] == ALERT_HOSTING_NOTE
    assert "error" in invalid


@pytest.mark.asyncio
async def test_pipeline_tool_errors_are_dicts(tmp_path):
    store = DealStore(tmp_path / "pipeline.db")
    with (
        patch("cre_mcp.tools.pipeline_tools.get_deal_store", return_value=store),
        patch(
            "cre_mcp.tools.pipeline_tools.analyze_deal",
            new=AsyncMock(return_value={"error": "unknown source"}),
        ),
    ):
        assert await add_to_pipeline("bad") == {"error": "unknown source"}
        assert await update_deal_stage("missing:1", "lead") == {
            "error": "unknown deal_id: missing:1"
        }
        assert "error" in await list_pipeline("won")


@pytest.mark.asyncio
async def test_phase13_tools_are_registered_and_total_is_forty_seven():
    tools = await mcp.get_tools()
    assert {
        "add_to_pipeline",
        "update_deal_stage",
        "list_pipeline",
        "save_search",
        "list_searches",
        "check_alerts",
    } <= set(tools)
    assert len(tools) == 47
