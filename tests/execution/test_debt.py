"""Hand-computed LTV/DSCR debt sizing and scenario toggles."""

import pytest

from cre_mcp.execution.debt import size_debt
from cre_mcp.underwriting.metrics import mortgage_constant
from tests.scoring.builders import deal_context, market_pack


def test_ltv_binding_bank_sizing_matches_hand_calculation():
    ctx = deal_context(price=1_000_000, noi=150_000)
    result = size_debt(
        ctx,
        "bank",
        ltv=0.65,
        rate=0.06,
        amort_years=25,
        min_dscr=1.25,
    )
    constant = mortgage_constant(0.06, 25)
    assert constant is not None
    expected_ltv = 650_000
    expected_dscr = 150_000 / (1.25 * constant)

    assert result.ltv_constraint == pytest.approx(expected_ltv)
    assert result.dscr_constraint == pytest.approx(expected_dscr)
    assert result.max_loan == pytest.approx(expected_ltv)
    assert result.binding_constraint == "ltv"
    assert result.equity_required == pytest.approx(350_000)
    assert result.dscr == pytest.approx(150_000 / (expected_ltv * constant))


def test_dscr_binding_bank_sizing_matches_hand_calculation():
    ctx = deal_context(price=1_000_000, noi=60_000)
    result = size_debt(
        ctx,
        "bank",
        ltv=65,
        rate=6,
        amort_years=25,
        min_dscr=1.25,
    )
    constant = mortgage_constant(0.06, 25)
    assert constant is not None
    expected = 60_000 / (1.25 * constant)

    assert result.max_loan == pytest.approx(expected)
    assert result.binding_constraint == "dscr"
    assert result.dscr == pytest.approx(1.25)
    assert result.annual_debt_service == pytest.approx(60_000 / 1.25)


def test_bridge_scenario_uses_interest_only_constant_and_scenario_toggles():
    ctx = deal_context(price=1_000_000, noi=100_000)
    result = size_debt(ctx, "bridge", ltv=0.70, rate=0.10, min_dscr=1.10)

    assert result.max_loan == pytest.approx(700_000)
    assert result.annual_debt_service == pytest.approx(70_000)
    assert result.dscr == pytest.approx(100_000 / 70_000)
    assert result.assumptions_used["interest_only"]["value"] is True
    assert result.cash_on_cash == pytest.approx(10.0)


def test_default_rate_is_anchored_to_covered_fred_metric():
    ctx = deal_context(
        price=2_000_000,
        noi=160_000,
        market=market_pack({"treasury_10yr": 4.25, "sofr": 4.40}),
    )
    result = size_debt(ctx, "agency")

    assert result.assumptions_used["rate_pct"]["value"] == pytest.approx(6.25)
    assert "treasury_10yr" in result.assumptions_used["rate_pct"]["source"]
    assert "200 bps" in result.assumptions_used["rate_pct"]["source"]
    assert "not a loan commitment" in result.guardrail


def test_missing_noi_degrades_to_ltv_only_with_visible_gap():
    ctx = deal_context(price=1_000_000, noi=None)
    result = size_debt(ctx, "bank")

    assert result.max_loan == pytest.approx(650_000)
    assert result.dscr_constraint is None
    assert result.dscr is None
    assert "noi_gap" in result.assumptions_used
