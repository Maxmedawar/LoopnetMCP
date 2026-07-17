"""Phase 12 MCP tool boundaries over a mocked enriched deal."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.tools.execution_tools import (
    closing_plan,
    due_diligence_plan,
    list_deals,
    save_deal,
)
from tests.scoring.builders import deal_context


@pytest.mark.asyncio
async def test_diligence_closing_save_and_list_tools_end_to_end(tmp_path):
    ctx = deal_context(property_type="retail", raw={"strategy": "nnn_retail"})
    store = DealStore(tmp_path / "tools.db")
    with (
        patch(
            "cre_mcp.tools.execution_tools._deal_context",
            new=AsyncMock(return_value=ctx),
        ),
        patch("cre_mcp.tools.execution_tools.get_deal_store", return_value=store),
    ):
        dd = await due_diligence_plan(
            "synthetic-1",
            dd_days=21,
            start_date="2026-07-13",
            source="fixture",
        )
        close = await closing_plan("synthetic-1", state="GA", source="fixture")
        saved = await save_deal("synthetic-1", source="fixture")
        listed = await list_deals()

    assert "error" not in dd
    assert dd["dd_days"] == 21
    assert {"tenant_estoppel", "snda"} <= {item["key"] for item in dd["items"]}
    assert close["closing_mode"] == "attorney-led"
    assert close["wire_fraud_warning"].startswith("WIRE-FRAUD STOP")
    assert saved == {"deal_id": "fixture:synthetic-1"}
    assert listed["count"] == 1
    assert listed["deals"][0]["dd_total"] == len(dd["items"])


@pytest.mark.asyncio
async def test_phase12_context_tools_return_error_dicts():
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(side_effect=ValueError("unknown source")),
    ):
        assert await due_diligence_plan("bad") == {"error": "unknown source"}
        assert await closing_plan("bad") == {"error": "unknown source"}
        assert await save_deal("bad") == {"error": "unknown source"}
