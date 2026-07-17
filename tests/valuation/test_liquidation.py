"""Forced-sale convention and carrying-cost checks."""

import pytest

from cre_mcp.valuation.liquidation import forced_sale_value


def test_discount_grid_is_cited_and_marketing_carry_is_deducted():
    result = forced_sale_value(
        market_value={"low": 1_000, "high": 1_200},
        marketing_period=3,
        market_liquidity="normal",
        cost_of_sale=0.10,
        carrying_costs={"monthly": 100},
    )

    assert result["discount_convention"]["discount_rate_range"] == {
        "low": 0.08,
        "high": 0.15,
    }
    assert "Internal forced-sale analytical convention" in result["convention_citation"]
    assert "not observed market evidence" in result["discount_convention"]["citation"]
    assert result["carrying_costs"]["total_over_marketing_range"] == {
        "low": 300,
        "high": 300,
    }
    assert result["net_forced_sale_value_range"]["low"] == pytest.approx(465)
    assert result["net_forced_sale_value_range"]["high"] == pytest.approx(693.6)
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )


def test_sale_cost_sequence_range_matches_advertised_tool_input():
    result = forced_sale_value(
        market_value=1_000,
        marketing_period=12,
        market_liquidity="high",
        cost_of_sale=[4, 6],
    )

    assert result["cost_of_sale"]["rate_range"] == {"low": 0.04, "high": 0.06}
    assert result["cost_of_sale"]["fixed_dollar_range"] == {"low": 0, "high": 0}
