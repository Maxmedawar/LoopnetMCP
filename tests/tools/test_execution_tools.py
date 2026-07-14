"""Offer and LOI MCP tool boundaries over a mocked enriched DealContext."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.server import mcp
from cre_mcp.tools.execution_tools import (
    draft_outreach,
    closing_plan,
    due_diligence_plan,
    find_contact,
    financing_options,
    generate_loi,
    handle_counter,
    list_deals,
    qualify_me,
    recommend_offer,
    save_deal,
    size_debt,
)
from tests.scoring.builders import deal_context, market_pack
from tests.expected import EXPECTED_TOOL_COUNT


def _context():
    return deal_context(
        price=1_100_000,
        noi=70_000,
        raw={
            "strategy": "nnn_retail",
            "tenant_credit_rating": "BBB",
            "lease_years_remaining": 12,
        },
        market=market_pack({"treasury_10yr": 4.0, "mortgage_rate": 6.5}),
    )


@pytest.mark.asyncio
async def test_recommend_offer_tool_uses_mocked_deal_context():
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(return_value=_context()),
    ) as build:
        result = await recommend_offer("31948105", strategy="nnn_retail")

    assert "error" not in result
    assert result["open_price"] < result["target_price"] < result["walk_price"]
    assert result["rationale"]
    assert result["key_terms"]["next_step_gate"]
    build.assert_awaited_once_with("31948105", "loopnet", "nnn_retail")


@pytest.mark.asyncio
async def test_generate_loi_defaults_to_recommended_target_and_accepts_overrides():
    ctx = _context()
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(return_value=ctx),
    ):
        recommended = await recommend_offer("31948105")
        result = await generate_loi(
            "31948105",
            earnest_money_pct=1.5,
            dd_days=25,
            closing_days=40,
            buyer_entity="Novice King LLC",
            state="TX",
        )

    assert "error" not in result
    assert result["price"] == recommended["target_price"]
    assert result["earnest_money"] == result["price"] * 0.015
    assert result["dd_days"] == 25
    assert result["closing_days"] == 40
    assert result["buyer_entity"] == "Novice King LLC"
    assert "NON-BINDING" in result["body_markdown"]


@pytest.mark.asyncio
async def test_execution_tools_return_error_dicts():
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(side_effect=ValueError("unknown source")),
    ):
        assert await recommend_offer("bad") == {"error": "unknown source"}
        assert await generate_loi("bad") == {"error": "unknown source"}
        assert await find_contact("bad") == {"error": "unknown source"}
        assert await draft_outreach("bad") == {"error": "unknown source"}
        assert await handle_counter("bad", "counter") == {"error": "unknown source"}
        assert await financing_options("bad") == {"error": "unknown source"}
        assert await qualify_me("bad", 1, 1) == {"error": "unknown source"}
        assert await size_debt("bad") == {"error": "unknown source"}
        assert await due_diligence_plan("bad") == {"error": "unknown source"}
        assert await closing_plan("bad") == {"error": "unknown source"}
        assert await save_deal("bad") == {"error": "unknown source"}


@pytest.mark.asyncio
async def test_execution_tools_are_registered_and_tool_count_matches_expected():
    tools = await mcp.get_tools()
    assert {
        "recommend_offer",
        "generate_loi",
        "find_contact",
        "draft_outreach",
        "handle_counter",
        "financing_options",
        "qualify_me",
        "size_debt",
        "due_diligence_plan",
        "closing_plan",
        "save_deal",
        "list_deals",
    } <= set(tools)
    assert len(tools) == EXPECTED_TOOL_COUNT


@pytest.mark.asyncio
async def test_contact_outreach_and_counter_tools_run_over_enriched_context():
    ctx = _context()
    ctx.listing.broker_name = "Jordan Broker"
    ctx.listing.broker_phone = "512-555-0100"
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(return_value=ctx),
    ):
        contact = await find_contact("31948105")
        outreach = await draft_outreach(
            "31948105",
            channel="email",
            angle="via_broker",
        )
        counter = await handle_counter(
            "31948105",
            "Seller counters at $1.2M with $50k earnest, 10 days DD, and the "
            "deposit goes hard day one.",
        )

    assert contact["broker"]["name"] == "Jordan Broker"
    assert outreach["recipient"] == "Jordan Broker"
    assert outreach["script"].endswith(outreach["guardrail"])
    assert counter["verdict"] in {"counter", "walk"}
    assert any("Day-one" in flag for flag in counter["red_flags"])


@pytest.mark.asyncio
async def test_financing_qualification_and_debt_tools_run_over_enriched_context():
    ctx = _context()
    with patch(
        "cre_mcp.tools.execution_tools._deal_context",
        new=AsyncMock(return_value=ctx),
    ):
        options = await financing_options("31948105")
        qualification = await qualify_me(
            "31948105",
            net_worth=2_000_000,
            liquid=2_000_000,
            experience_deals=1,
            credit_tier="good",
        )
        debt = await size_debt(
            "31948105",
            scenario="bank",
            ltv=65,
            rate=7,
            amort_years=25,
            min_dscr=1.25,
        )

    sba = next(option for option in options if option["type"] == "sba_504_7a")
    assert sba["eligible"] is False
    assert qualification["verdict"] == "qualifies"
    assert all("pass" in gate for gate in qualification["gates"])
    assert debt["max_loan"] == debt["proceeds"]
    assert debt["binding_constraint"] in {"ltv", "dscr"}
    assert "not a loan commitment" in debt["guardrail"]
