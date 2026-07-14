"""Deterministic after-tax return math tests."""

import pytest

from cre_mcp.tax.after_tax import after_tax_returns
from tests.scoring.builders import deal_context


def _unlevered_result(**overrides):
    assumptions = {
        "ltv": 0,
        "land_pct": 0.20,
        "marginal_rate": 0.37,
        "capital_gains_rate": 0.20,
        "annual_appreciation_rate": 0.05,
        "selling_cost_pct": 0,
        "hold_years": 5,
        **overrides,
    }
    return after_tax_returns(
        deal_context(property_type="retail", price=1_000_000, noi=100_000),
        assumptions,
    )


def test_commercial_depreciation_and_annual_shield_match_hand_math():
    result = _unlevered_result(annual_appreciation_rate=0)
    year_one = result.depreciation_schedule[0]
    annual_depreciation = 800_000 / 39

    assert result.land_basis == 200_000
    assert result.improvement_basis == 800_000
    assert result.recovery_period_years == 39
    assert year_one.building_depreciation == pytest.approx(annual_depreciation, abs=0.01)
    assert year_one.potential_tax_shield == pytest.approx(
        annual_depreciation * 0.37,
        abs=0.01,
    )
    assert result.assumptions_used["land_pct"]["value"] == 0.20
    assert "CPA" in result.cpa_gate


def test_residential_uses_27_5_year_recovery_and_optional_cost_seg_accelerates():
    residential = after_tax_returns(
        deal_context(
            property_type="multifamily",
            price=1_000_000,
            noi=100_000,
            units=10,
        ),
        {
            "ltv": 0,
            "land_pct": 0.20,
            "hold_years": 1,
            "cost_seg": True,
            "bonus_pct": 0.50,
        },
    )
    year_one = residential.depreciation_schedule[0]

    assert residential.recovery_period_years == 27.5
    assert year_one.bonus_depreciation == 120_000
    assert year_one.total_depreciation > 800_000 / 27.5
    assert residential.assumptions_used["bonus_pct"] == 0.50
    assert "qualified study" in residential.cpa_gate


def test_section_1250_recapture_is_capped_and_taxed_at_twenty_five_percent():
    result = _unlevered_result()

    assert result.unrecaptured_1250_gain == pytest.approx(
        result.total_building_depreciation,
        abs=0.01,
    )
    assert result.unrecaptured_1250_rate == 0.25
    assert result.unrecaptured_1250_tax == pytest.approx(
        result.unrecaptured_1250_gain * 0.25,
        abs=0.01,
    )
    assert result.total_gain > result.unrecaptured_1250_gain


def test_after_tax_irr_and_multiple_are_below_pre_tax_when_sale_has_gain():
    result = _unlevered_result()

    assert result.pre_tax_irr_pct is not None
    assert result.after_tax_irr_pct is not None
    assert result.after_tax_irr_pct < result.pre_tax_irr_pct
    assert result.after_tax_equity_multiple < result.pre_tax_equity_multiple
    assert result.total_exit_tax > 0


def test_missing_price_or_noi_and_bonus_without_cost_seg_are_honest_errors():
    with pytest.raises(ValueError, match="purchase price"):
        after_tax_returns(deal_context(price=None, noi=100_000))
    with pytest.raises(ValueError, match="NOI"):
        after_tax_returns(deal_context(price=1_000_000, noi=None))
    with pytest.raises(ValueError, match="requires cost_seg"):
        _unlevered_result(bonus_pct=1, cost_seg=False)
