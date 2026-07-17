"""Plain wrapper contract tests."""

from cre_mcp.scenarios.tools import (
    breakeven_analysis,
    model_lease_up,
    sensitivity_drivers,
    stress_test_deal,
)


def _deal():
    return {
        "price": 100_000,
        "noi": 10_000,
        "gross_potential_rent": 15_000,
        "occupancy": 0.9,
        "other_income": 0,
        "operating_expenses": 3_500,
        "rentable_sf": 1_000,
        "loan_amount": 0,
        "hold_years": 1,
        "exit_cap": 0.1,
    }


def test_plain_wrappers_all_return_honesty_and_assumptions_blocks():
    results = [
        stress_test_deal(_deal(), "base"),
        sensitivity_drivers(_deal(), {"exit_cap": 0.01}),
        breakeven_analysis(_deal(), 1.25),
        model_lease_up(
            [
                {
                    "name": "A",
                    "sf": 1_000,
                    "available_month": 0,
                    "annual_rent": 12_000,
                }
            ],
            1,
            0,
            0,
            0,
            0,
            0,
        ),
    ]

    for result in results:
        assert "honesty_label" in result
        assert "assumptions" in result
