"""Hand-computed structured term-sheet comparisons."""

import pytest

from cre_mcp.debt.termsheet import QUOTED_TERMS_WARNING, TermSheet, compare_term_sheets
from cre_mcp.underwriting.metrics import annual_debt_service


def _sheet(lender: str, proceeds: float, rate: float, **overrides) -> TermSheet:
    values = {
        "lender": lender,
        "proceeds": proceeds,
        "rate": rate,
        "io_months": 0,
        "amort_years": 25,
        "term_years": 5,
        "origination_fee_pct": 0.01,
        "exit_fee_pct": 0.0,
        "other_fees": 0.0,
        "recourse": "partial",
        "covenants": {
            "min_dscr": 1.10,
            "max_ltv": 0.75,
            "cash_sweep_trigger": 1.15,
            "reserves": {"ti_lc": 0, "capex": 0, "tax_insurance": 0},
        },
        "prepay": {"type": "stepdown", "params": [5, 4, 3, 2, 1]},
        "extension_options": [],
        "rate_cap_required": False,
    }
    values.update(overrides)
    return TermSheet(**values)


def test_all_in_cost_and_io_vs_amortizing_dscr_are_hand_computed():
    sheet = _sheet(
        "Hand Check Bank",
        1_000_000,
        0.06,
        io_months=12,
        origination_fee_pct=1.0,
        exit_fee_pct=0.5,
        other_fees=5_000,
    )
    result = compare_term_sheets(
        [sheet],
        {
            "noi": 120_000,
            "price": 1_500_000,
            "hold_years": 5,
            "exit_assumptions": {"stabilized_noi": 120_000},
        },
    )
    row = result["comparisons"][0]
    amortizing = annual_debt_service(1_000_000, 0.06, 25)
    assert amortizing is not None

    assert row["all_in_cost"] == pytest.approx(0.06 + 20_000 / 1_000_000 / 5)
    assert row["year_1_debt_service"] == pytest.approx(60_000)
    assert row["stabilized_debt_service"] == pytest.approx(amortizing)
    assert row["year_1_dscr"] == pytest.approx(2.0)
    assert row["stabilized_dscr"] == pytest.approx(120_000 / amortizing)
    assert result["warning"] == QUOTED_TERMS_WARNING
    assert result["lender_ledger_pointer"] == "lender_track_record"


def test_rankings_change_with_explicit_objective():
    sheet_a = _sheet(
        "A",
        700_000,
        0.07,
        io_months=12,
        prepay={"type": "open", "params": {}},
        extension_options=[{"years": 1}, {"years": 1}],
    )
    sheet_b = _sheet(
        "B",
        600_000,
        0.05,
        prepay={"type": "yield_maintenance", "params": {}},
    )
    result = compare_term_sheets(
        [sheet_a, sheet_b],
        {
            "noi": 100_000,
            "price": 1_000_000,
            "hold_years": 5,
            "exit_assumptions": {"stabilized_noi": 110_000},
        },
    )

    assert result["ranked_verdicts"]["max_proceeds"]["winner"] == "A"
    assert result["ranked_verdicts"]["min_cost"]["winner"] == "B"
    assert result["ranked_verdicts"]["max_flexibility"]["winner"] == "A"
    assert result["overall_ranking"] is None


def test_missing_fee_and_stabilized_noi_are_explicit_not_computable():
    incomplete = _sheet("Incomplete", 500_000, 0.06, other_fees=None)
    result = compare_term_sheets(
        [incomplete],
        {"noi": 75_000, "price": 1_000_000, "hold_years": 5, "exit_assumptions": {}},
    )
    row = result["comparisons"][0]

    assert row["all_in_cost"] is None
    assert row["all_in_cost_detail"]["status"] == "not_computable"
    assert "other_fees" in row["missing_inputs"]
    assert "deal.exit_assumptions.stabilized_noi" in row["missing_inputs"]
    assert row["stabilized_dscr"] is None


def test_floating_rate_needs_caller_supplied_index_value():
    sheet = _sheet(
        "Floating",
        500_000,
        {"type": "floating", "index": "SOFR", "spread_bps": 250},
        rate_cap_required=True,
    )
    result = compare_term_sheets(
        [sheet],
        {
            "noi": 75_000,
            "price": 1_000_000,
            "hold_years": 5,
            "exit_assumptions": {"stabilized_noi": 80_000},
        },
    )
    row = result["comparisons"][0]

    assert row["all_in_cost"] is None
    assert "rate.index_rate" in row["missing_inputs"]
    assert any("cap premium" in note for note in row["risk_notes"])
