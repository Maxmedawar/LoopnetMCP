"""Cash-to-close, sponsor capacity, and first-timer qualification gates."""

import pytest

from cre_mcp.execution.debt import size_debt
from cre_mcp.execution.qualify import qualify_me
from tests.scoring.builders import deal_context, market_pack


def _agency_ctx():
    return deal_context(
        property_type="multifamily",
        price=1_000_000,
        units=12,
        noi=100_000,
        raw={"occupancy_rate": 0.95, "strategy": "core"},
        market=market_pack({"treasury_10yr": 4.0, "sofr": 4.2}),
    )


def test_first_timer_with_cash_and_net_worth_needs_experience_partner():
    result = qualify_me(
        _agency_ctx(),
        {
            "net_worth": 2_000_000,
            "liquid": 1_000_000,
            "experience_deals": 0,
            "credit_tier": "good",
        },
    )

    gates = {gate.name: gate for gate in result.gates}
    assert result.selected_scenario == "agency"
    assert gates["net_worth"].passed is True
    assert gates["post_close_liquidity"].passed is True
    assert gates["sponsor_experience"].passed is False
    assert result.verdict == "needs_partner"
    assert any("co-sponsor" in gap for gap in result.gaps)


def test_cash_to_close_is_down_plus_closing_costs_plus_nine_month_reserves():
    ctx = deal_context(
        property_type="retail",
        price=1_000_000,
        noi=100_000,
        market=market_pack({"treasury_10yr": 4.0, "sofr": 4.2}),
    )
    debt = size_debt(ctx, "bank")
    result = qualify_me(
        ctx,
        {"net_worth": 2_000_000, "liquid": 2_000_000, "experience_deals": 1},
    )
    expected_close = 1_000_000 * 0.03
    expected_reserves = debt.annual_debt_service / 12 * 9
    expected = debt.equity_required + expected_close + expected_reserves

    assert result.breakdown["closing_costs"] == pytest.approx(expected_close)
    assert result.breakdown["reserves"] == pytest.approx(expected_reserves)
    assert result.cash_to_close == pytest.approx(expected)
    assert result.verdict == "qualifies"


def test_liquidity_shortfall_is_blunt_and_does_not_spend_reserves():
    result = qualify_me(
        _agency_ctx(),
        {"net_worth": 2_000_000, "liquid": 50_000, "experience_deals": 3},
    )
    assert result.verdict == "short_on_cash"
    assert any("short by" in gap for gap in result.gaps)
    assert "Do not stretch reserves" in result.guidance


def test_agency_net_worth_below_loan_calls_for_balance_sheet_partner():
    result = qualify_me(
        _agency_ctx(),
        {"net_worth": 100_000, "liquid": 1_000_000, "experience_deals": 3},
    )
    assert result.verdict == "needs_partner"
    assert any("balance-sheet guarantor" in gap for gap in result.gaps)
    assert "not a loan commitment" in result.guardrail


def test_low_credit_tier_is_not_lender_ready():
    result = qualify_me(
        _agency_ctx(),
        {
            "net_worth": 2_000_000,
            "liquid": 1_000_000,
            "experience_deals": 3,
            "credit_tier": "poor",
        },
    )
    assert result.verdict == "no"
    assert any(gate.name == "credit_tier" and not gate.passed for gate in result.gates)
