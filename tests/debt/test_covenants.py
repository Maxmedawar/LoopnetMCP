"""Exact breach timing and NOI-cushion projection tests."""

import pytest

from cre_mcp.debt.covenants import VALUATION_REQUIRED, covenant_forecast


def _loan():
    return {
        "balance": 1_000_000,
        "rate": 0.05,
        "io_months": 120,
        "amort_years": 30,
        "term_years": 10,
        "covenants": {
            "min_dscr": 1.25,
            "max_ltv": 0.75,
            "min_debt_yield": 0.055,
            "cash_sweep_trigger": 1.30,
        },
    }


def test_declining_noi_first_breach_and_cash_sweep_period_are_exact():
    result = covenant_forecast(
        _loan(),
        [
            {"period": "Y1", "noi": 70_000},
            {"period": "Y2", "noi": 65_000},
            {"period": "Y3", "noi": 60_000},
        ],
    )

    assert result["first_breach_period"]["dscr"] == "Y3"
    assert result["periods"][0]["dscr"] == pytest.approx(1.40)
    assert result["periods"][1]["cash_sweep_active"] is False
    assert result["periods"][2]["cash_sweep_active"] is True
    assert result["cash_sweep_activation_timeline"][0]["period"] == "Y3"
    assert result["early_warnings"][0]["covenant"] == "dscr"


def test_dscr_noi_decline_cushion_is_hand_computed():
    result = covenant_forecast(_loan(), [{"period": 1, "noi": 70_000}])
    cushion = result["periods"][0]["cushion"]["dscr_noi_decline"]

    assert cushion["threshold_noi"] == pytest.approx(62_500)
    assert cushion["amount"] == pytest.approx(7_500)
    assert cushion["pct_of_current_noi"] == pytest.approx(7_500 / 70_000)


def test_ltv_is_visibly_valuation_dependent_and_growth_path_is_labeled():
    result = covenant_forecast(_loan(), base_noi=70_000, growth=-0.05, periods=2)

    assert result["status"] == "projected"
    assert result["valuation_dependent_covenants"] == VALUATION_REQUIRED
    assert result["periods"][0]["ltv_status"] == VALUATION_REQUIRED
    assert "Projection" in result["periods"][0]["projection_label"]
    assert result["periods"][1]["projected_noi"] == pytest.approx(66_500)


def test_missing_noi_path_does_not_invent_growth():
    result = covenant_forecast(_loan())

    assert result["status"] == "not_computable"
    assert "base_noi" in result["missing_inputs"]
    assert "growth" in result["missing_inputs"]
    assert result["periods"] == []
