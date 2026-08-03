"""Hand-computed below-market debt present value and monotonicity."""

import pytest

from cre_mcp.debt.assumable import value_assumable_debt


def _existing(rate: float):
    return {
        "balance": 100_000,
        "rate": rate,
        "io_remaining": 12,
        "amort": 30,
        "maturity": 10,
        "assumption_fee": 0,
        "approval_risk_note": "Consent standards are not yet confirmed.",
    }


def _market(rate: float = 0.05):
    return {"rate": rate, "ltv": 0.70, "io": 12, "amort": 30}


def test_simple_io_payment_savings_pv_is_hand_computed():
    result = value_assumable_debt(_existing(0.02), _market(), price=200_000, hold_years=1)
    monthly_discount_rate = 0.05 / 12
    expected = sum(250 / (1 + monthly_discount_rate) ** month for month in range(1, 13))

    assert result["pv_payment_savings"] == pytest.approx(expected)
    assert result["terminal_balance_adjustment"] == pytest.approx(0)
    assert result["net_assumable_debt_value"] == pytest.approx(expected)
    assert result["debt_adjusted_effective_price"] == pytest.approx(200_000 - expected)
    assert result["proceeds_gap_vs_new_debt"] == pytest.approx(40_000)
    assert result["equity_gap"] == pytest.approx(40_000)


def test_larger_rate_gap_increases_assumable_value():
    larger_gap = value_assumable_debt(_existing(0.01), _market(), 200_000, 1)
    smaller_gap = value_assumable_debt(_existing(0.03), _market(), 200_000, 1)

    assert larger_gap["net_assumable_debt_value"] > smaller_gap["net_assumable_debt_value"]


def test_missing_market_ltv_is_not_computable():
    market = _market()
    market.pop("ltv")
    result = value_assumable_debt(_existing(0.02), market, 200_000, 1)

    assert result["status"] == "not_computable"
    assert "market.ltv" in result["missing_inputs"]
    assert result["pv_payment_savings"] is None
    assert result["proceeds_gap_vs_new_debt"] is None
