"""Phase 20 MCP boundary and registration tests."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.models.enrichment import ListingFacts
from cre_mcp.server import mcp
from cre_mcp.tools.ops_tools import after_tax_returns, operating_playbook
from tests.scoring.builders import deal_context


def _analysis_payload():
    ctx = deal_context(
        source_id="ops-tool-deal",
        property_type="retail",
        price=1_000_000,
        noi=100_000,
        raw={"closing_date": "2026-08-01"},
    )
    ctx.facts = ListingFacts(
        strategy_hint="nnn_retail",
        lease_years_remaining=10,
        rent_escalations=2,
        nnn_purity="absolute",
    )
    return {
        "listing": ctx.listing.model_dump(mode="json"),
        "facts": ctx.facts.model_dump(mode="json"),
        "underwriting": ctx.underwriting.model_dump(mode="json"),
        "scores": [],
    }


@pytest.mark.asyncio
async def test_after_tax_returns_tool_uses_analyzed_deal_and_cpa_gates():
    mocked = AsyncMock(return_value=_analysis_payload())
    with patch("cre_mcp.tools.ops_tools.analyze_deal", new=mocked):
        result = await after_tax_returns(
            "ops-tool-deal",
            marginal_rate=0.37,
            hold_years=5,
            source="fixture",
        )

    assert result["recovery_period_years"] == 39
    assert all(
        result[key] is not None
        for key in (
            "pre_tax_irr",
            "after_tax_irr",
            "depreciation_annual",
            "recapture_1250",
        )
    )
    assert result["after_tax_irr"] < result["pre_tax_irr"]
    assert result["after_tax_irr_pct"] < result["pre_tax_irr_pct"]
    assert result["unrecaptured_1250_rate"] == 0.25
    assert "CPA" in result["cpa_gate"]
    mocked.assert_awaited_once_with("ops-tool-deal", source="fixture")


@pytest.mark.asyncio
async def test_operating_playbook_tool_persists_and_surfaces_reassessment(tmp_path):
    mocked = AsyncMock(return_value=_analysis_payload())
    store = DealStore(tmp_path / "ops-tools.db")
    with (
        patch("cre_mcp.tools.ops_tools.analyze_deal", new=mocked),
        patch("cre_mcp.tools.ops_tools.get_deal_store", return_value=store),
    ):
        result = await operating_playbook("ops-tool-deal", source="fixture")

    assert result["persistence_status"] == "saved"
    assert any("REASSESSMENT" in item["label"] for item in result["recurring"])
    assert any(item["key"] == "lease_expiration" for item in result["critical_dates"])
    assert await store.get_ops_events(result["deal_id"])


@pytest.mark.asyncio
async def test_ops_tool_errors_are_error_dicts():
    with patch(
        "cre_mcp.tools.ops_tools.analyze_deal",
        new=AsyncMock(return_value={"error": "listing unavailable"}),
    ):
        assert await after_tax_returns("missing") == {"error": "listing unavailable"}
        assert await operating_playbook("missing") == {"error": "listing unavailable"}


@pytest.mark.asyncio
async def test_phase20_tools_are_registered_and_total_is_fifty():
    tools = await mcp.get_tools()
    assert {"after_tax_returns", "operating_playbook"} <= set(tools)
    assert len(tools) == 50
