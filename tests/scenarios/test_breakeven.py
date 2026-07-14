"""Exact break-even threshold tests."""

import pytest

from cre_mcp.scenarios.breakeven import analyze_breakevens


def _deal(**overrides):
    deal = {
        "price": 1_000_000,
        "noi": 120_000,
        "gross_potential_rent": 200_000,
        "occupancy": 0.90,
        "other_income": 0,
        "operating_expenses": 60_000,
        "rentable_sf": 10_000,
        "loan_amount": 600_000,
        "annual_interest_rate": 0.10,
        "amortization_years": 30,
        "io_months": 12,
        "hold_years": 1,
    }
    deal.update(overrides)
    return deal


def test_all_thresholds_match_hand_computed_interest_only_case():
    result = analyze_breakevens(_deal(), target_dscr=1.25)

    assert result["break_even_noi"] == pytest.approx(60_000)
    assert result["target_dscr_noi"] == pytest.approx(75_000)
    assert result["break_even_occupancy"] == pytest.approx(60.0)
    assert result["break_even_rent_per_sf"] == pytest.approx(13.333333333333334)
    assert result["target_dscr_rent_per_sf"] == pytest.approx(15.0)
    assert result["remaining_loan_balance_at_exit"] == pytest.approx(600_000)
    assert result["break_even_exit_price"] == pytest.approx(940_000)
    assert result["rate_ceiling_dscr_1_0"] == pytest.approx(0.20)
    assert result["rate_ceiling_target_dscr"] == pytest.approx(0.16)


def test_break_even_occupancy_reuses_underwriting_percentage_vocabulary():
    result = analyze_breakevens(_deal(), target_dscr=1.25)

    assert result["break_even_occupancy_percent"] == 60.0
    assert result["assumptions"]["rent_per_sf_basis"].startswith("annual")


def test_target_thresholds_remain_missing_without_target_input():
    result = analyze_breakevens(_deal())

    assert result["target_dscr"] is None
    assert result["target_dscr_noi"] is None
    assert result["rate_ceiling_target_dscr"] is None
    assert any("target_dscr is missing" in message for message in result["not_computable"])


def test_all_cash_deal_marks_debt_break_evens_not_applicable():
    result = analyze_breakevens(_deal(loan_amount=0), target_dscr=1.25)

    assert result["break_even_noi"] is None
    assert result["rate_ceiling_dscr_1_0"] is None
    assert any("deal has no debt" in message for message in result["not_computable"])


def test_missing_rent_facts_do_not_get_defaulted():
    deal = _deal()
    del deal["other_income"]
    result = analyze_breakevens(deal, target_dscr=1.25)

    assert result["break_even_rent_per_sf"] is None
    assert any("other_income" in message for message in result["not_computable"])


def test_zero_noi_has_no_nonnegative_rate_ceiling():
    result = analyze_breakevens(_deal(noi=0), target_dscr=1.25)

    assert result["rate_ceiling_dscr_1_0"] is None
    assert any("NOI and target DSCR must be positive" in message for message in result["not_computable"])
