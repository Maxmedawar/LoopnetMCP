"""Hand-computed waterfall allocation tests."""

import pytest

from cre_mcp.capital.waterfall import model_waterfall


def test_pref_capital_catchup_promote_and_returns_match_hand_calculation():
    result = model_waterfall(
        {"deal_ref": "fixture:one", "total_equity": 1_000_000},
        {
            "annual_cash_flows": [1_500_000],
            "pref": 8,
            "gp_promote": 20,
            "lp_equity_pct": 100,
            "catch_up": True,
        },
    )
    year = result.years[0]

    assert year.lp_preferred_return == 80_000
    assert year.lp_return_of_capital == 1_000_000
    assert year.gp_catch_up == 20_000
    assert year.lp_residual == 320_000
    assert year.gp_residual == 80_000
    assert result.lp_cash_flows == [-1_000_000, 1_400_000]
    assert result.gp_cash_flows == [0, 100_000]
    assert result.lp_irr_pct == pytest.approx(40.0)
    assert result.lp_equity_multiple == pytest.approx(1.4)
    assert result.gp_promote_earned == 100_000
    assert "not promises" in result.anti_fraud_warning.casefold()
    assert "securities attorney" in result.guardrail


def test_unpaid_pref_carries_and_tiered_split_changes_after_hurdle():
    result = model_waterfall(
        {"deal_ref": "fixture:tier", "total_equity": 100_000},
        {
            "annual_cash_flows": [4_000, 156_000],
            "pref": 8,
            "gp_promote": 20,
            "lp_equity_pct": 100,
            "catch_up": False,
            "tiered_splits": [
                {"lp_irr_hurdle": 10, "lp_split": 60, "gp_split": 40}
            ],
        },
    )

    assert result.years[0].lp_preferred_return == 4_000
    assert result.years[0].unpaid_lp_preferred_return == 4_000
    assert result.years[1].lp_preferred_return == 12_000
    assert result.years[1].lp_return_of_capital == 100_000
    assert result.years[1].gp_residual > 0
    assert result.assumptions_used["tiered_splits"][0]["lp_split"] == 0.6


def test_waterfall_refuses_performance_guarantee_and_invalid_economics():
    with pytest.raises(ValueError, match="performance guarantees"):
        model_waterfall(
            {"total_equity": 100_000},
            {"annual_cash_flows": [120_000], "guaranteed_return": "12%"},
        )
    with pytest.raises(ValueError, match="below 100%"):
        model_waterfall(
            {"total_equity": 100_000},
            {"annual_cash_flows": [120_000], "gp_promote": 100},
        )
