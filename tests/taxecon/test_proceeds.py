"""Seller-proceeds waterfall, prepay, and transfer-tax tests."""

import pytest

from cre_mcp.taxecon.proceeds import (
    TRANSFER_TAX_REGISTRY,
    estimate_prepay_penalty,
    net_sale_proceeds,
    transfer_tax_estimate,
)


def test_proceeds_waterfall_base_arithmetic_is_hand_computable():
    result = net_sale_proceeds(
        price=1_000_000,
        loan_balance=400_000,
        prepay={"type": "none", "params": {}},
        commission_pct=5,
        state="CA",
        other_costs=10_000,
        credits=5_000,
        reserves_released=2_000,
    )

    # 1,000,000 - 400,000 - 50,000 - 1,100 - 10,000 + 5,000 + 2,000
    assert result["net_proceeds"]["base"] == 545_900
    assert result["transfer_tax"]["amount"]["base"] == 1_100
    assert result["status"] == "ESTIMATE"
    assert len(result["waterfall"]) == 8


def test_prepay_none_is_zero():
    result = estimate_prepay_penalty(500_000, {"type": "none", "params": {}})
    assert result["amount"] == {"low": 0.0, "base": 0.0, "high": 0.0}


def test_prepay_stepdown_uses_current_contractual_percentage():
    result = estimate_prepay_penalty(
        500_000,
        {"type": "stepdown", "params": {"penalty_pct": 2}},
    )
    assert result["amount"]["base"] == 10_000
    assert result["rate"] == pytest.approx(0.02)


def test_yield_maintenance_has_range_when_rate_inputs_exist():
    result = estimate_prepay_penalty(
        500_000,
        {
            "type": "yield_maintenance",
            "params": {"note_rate": 6, "treasury_rate": 4, "remaining_years": 5},
        },
    )

    assert result["status"] == "ESTIMATE"
    assert result["amount"]["low"] == 43_750
    assert result["amount"]["base"] == 50_000
    assert result["amount"]["high"] == 56_250
    assert "Simplified" in result["method"]


def test_yield_maintenance_without_rate_inputs_is_not_computable():
    result = estimate_prepay_penalty(
        500_000,
        {"type": "yield_maintenance", "params": {"remaining_years": 5}},
    )

    assert result["status"] == "NOT_COMPUTABLE"
    assert result["amount"]["base"] == "UNKNOWN"
    assert "note_rate" in result["missing_inputs"]
    assert "reinvestment_rate/treasury_rate" in result["missing_inputs"]


def test_defeasance_uses_supplied_estimate_and_never_claims_quote_precision():
    result = estimate_prepay_penalty(
        1_000_000,
        {"type": "defeasance", "params": {"estimated_cost": 100_000}},
    )

    assert result["amount"] == {"low": 90_000.0, "base": 100_000.0, "high": 110_000.0}
    assert "live quote" in result["method"]


def test_defeasance_without_cost_input_is_not_computable():
    result = estimate_prepay_penalty(
        1_000_000,
        {"type": "defeasance", "params": {}},
    )
    assert result["status"] == "NOT_COMPUTABLE"
    assert result["amount"]["base"] == "UNKNOWN"


def test_transfer_tax_registry_lookup_and_tx_zero():
    ca = transfer_tax_estimate(1_000_000, "CA")
    tx = transfer_tax_estimate(1_000_000, "TX")

    assert TRANSFER_TAX_REGISTRY["CA"].rate == pytest.approx(0.0011)
    assert ca["amount"]["base"] == 1_100
    assert tx["amount"]["base"] == 0
    assert tx["rule"]["source_citation"]
    assert tx["rule"]["last_verified"] == "2026-07"


def test_unknown_transfer_tax_makes_net_unknown_instead_of_assuming_zero():
    result = net_sale_proceeds(
        price=1_000_000,
        loan_balance=400_000,
        prepay={"type": "none", "params": {}},
        commission_pct=5,
        state="ID",
        other_costs=10_000,
        credits=0,
        reserves_released=0,
    )

    assert result["transfer_tax"]["status"] == "UNKNOWN"
    assert result["transfer_tax"]["amount"]["base"] == "UNKNOWN"
    assert result["net_proceeds"]["base"] == "UNKNOWN"
    assert result["status"] == "UNKNOWN"


def test_unknown_prepay_penalty_makes_net_unknown():
    result = net_sale_proceeds(
        price=1_000_000,
        loan_balance=400_000,
        prepay={"type": "yield_maintenance", "params": {}},
        commission_pct=5,
        state="TX",
        other_costs=0,
        credits=0,
        reserves_released=0,
    )
    assert result["prepayment_penalty"]["status"] == "NOT_COMPUTABLE"
    assert result["net_proceeds"]["base"] == "UNKNOWN"


def test_tax_profile_returns_hook_without_reimplementing_after_tax_math():
    result = net_sale_proceeds(
        1_000_000,
        0,
        {"type": "none", "params": {}},
        0,
        "TX",
        0,
        0,
        0,
        tax_profile={"adjusted_basis": 500_000},
    )
    assert result["after_tax_hook"]["module"] == "cre_mcp.ops.after_tax_returns"
    assert result["after_tax_hook"]["status"] == "DELEGATED_NOT_CALCULATED"

