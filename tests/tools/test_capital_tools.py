"""Phase 19 capital MCP boundary and registration tests."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.server import mcp
from cre_mcp.tools.capital_tools import (
    add_investor,
    check_solicitation,
    draft_form_d,
    draft_ppm,
    list_investors,
    model_waterfall,
    record_commitment,
)
from tests.scoring.builders import deal_context


def _analysis_payload():
    ctx = deal_context(source_id="capital-deal", price=2_500_000, noi=177_500)
    return {
        "listing": ctx.listing.model_dump(mode="json"),
        "underwriting": ctx.underwriting.model_dump(mode="json"),
        "scores": [],
    }


@pytest.mark.asyncio
async def test_investor_crm_tools_persist_and_hard_gate(tmp_path):
    store = DealStore(tmp_path / "capital.db")
    deal_id = await store.save_deal(deal_context(source_id="capital-deal").listing)
    assert deal_id is not None
    with patch("cre_mcp.tools.capital_tools.get_deal_store", return_value=store):
        investor = await add_investor(
            "Jordan LP",
            accredited=True,
            relationship="preexisting",
            contact="jordan@example.test",
        )
        commitment = await record_commitment(
            deal_id,
            investor["investor_id"],
            250_000,
        )
        listed = await list_investors()

    assert "HARD GATE" in investor["guardrail"]
    assert commitment["status"].startswith("NON-BINDING")
    assert "BEFORE" in commitment["guardrail"]
    assert listed["count"] == 1
    assert listed["total_indicated"] == 250_000


@pytest.mark.asyncio
async def test_compliance_tool_blocks_506b_and_506c_violations():
    public = await check_solicitation("506b", "advertise_publicly")
    unverified = await check_solicitation(
        "506c",
        {
            "action": "accept_investor",
            "accepting_money": True,
            "accredited": True,
            "accreditation_verified": False,
        },
    )

    assert public["allowed"] is False
    assert unverified["allowed"] is False
    assert "self-certification" in unverified["why"]


@pytest.mark.asyncio
async def test_waterfall_and_ppm_tools_use_analyzed_deal():
    mocked = AsyncMock(return_value=_analysis_payload())
    with patch("cre_mcp.tools.capital_tools.analyze_deal", new=mocked):
        waterfall = await model_waterfall(
            "capital-deal",
            total_equity=1_000_000,
            annual_cash_flow=100_000,
            exit_equity_proceeds=1_000_000,
            hold_years=1,
            lp_equity_pct=100,
            source="fixture",
        )
        ppm = await draft_ppm(
            "capital-deal",
            issuer_name="Congress Investors LLC",
            target_raise=1_000_000,
            source="fixture",
        )

    assert waterfall["lp_equity_multiple"] == pytest.approx(1.08)
    assert waterfall["gp_promote_earned"] == 20_000
    assert "MODELED OR TARGET" in waterfall["anti_fraud_warning"]
    assert ppm["status"].startswith("DRAFT")
    assert "Risk factors" in ppm["body_markdown"]
    assert ppm["preliminary_compliance_check"]["allowed"] is True
    assert mocked.await_count == 2


@pytest.mark.asyncio
async def test_form_d_tool_is_draft_and_calendars_deadline():
    result = await draft_form_d(
        "Congress Investors LLC",
        "TX",
        1_000_000,
        mode="506c",
        first_sale_date="2026-07-13",
        amount_sold=100_000,
    )

    assert result["status"].startswith("DRAFT")
    assert result["data"]["form_d_due_date_estimate"] == "2026-07-28"
    assert result["data"]["remaining_to_be_sold"] == 900_000
    assert "NOT FILED" in result["body_markdown"]


@pytest.mark.asyncio
async def test_capital_tool_errors_are_dicts(tmp_path):
    store = DealStore(tmp_path / "capital.db")
    with patch("cre_mcp.tools.capital_tools.get_deal_store", return_value=store):
        assert "error" in await add_investor(" ")
        assert "error" in await record_commitment("missing", 999, 100_000)
    assert "error" in await check_solicitation("bad", "advertise")
    assert "error" in await draft_form_d("Issuer", "TX", -1)
    with patch(
        "cre_mcp.tools.capital_tools.analyze_deal",
        new=AsyncMock(return_value={"error": "listing unavailable"}),
    ):
        assert await model_waterfall("missing") == {"error": "listing unavailable"}
        assert await draft_ppm("missing") == {"error": "listing unavailable"}


@pytest.mark.asyncio
async def test_capital_tools_registered_and_total_is_sixty_one():
    tools = await mcp.get_tools()
    assert {
        "add_investor",
        "list_investors",
        "record_commitment",
        "check_solicitation",
        "model_waterfall",
        "draft_ppm",
        "draft_form_d",
    } <= set(tools)
    assert len(tools) == 61
