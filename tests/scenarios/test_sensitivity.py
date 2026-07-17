"""Tornado ranking and evidence-label tests."""

from cre_mcp.scenarios.sensitivity import tornado


def _deal():
    return {
        "price": 1_000_000,
        "noi": 100_000,
        "gross_potential_rent": 150_000,
        "occupancy": 0.90,
        "other_income": 0,
        "operating_expenses": 35_000,
        "loan_amount": 600_000,
        "annual_interest_rate": 0.06,
        "amortization_years": 30,
        "io_months": 0,
        "hold_years": 5,
        "exit_cap": 0.07,
    }


def test_drivers_rank_by_absolute_irr_delta_and_report_dscr_delta():
    result = tornado(
        _deal(),
        {
            "rent": 0.10,
            "exit_cap": [-0.01, 0.01],
            "opex": {"low": -0.10, "high": 0.10},
            "interest_rate": 0.01,
        },
    )
    drivers = result["ranked_drivers"]

    assert [driver["rank"] for driver in drivers] == [1, 2, 3, 4]
    assert [driver["delta_irr"] for driver in drivers] == sorted(
        [driver["delta_irr"] for driver in drivers], reverse=True
    )
    assert all(driver["delta_dscr"] is not None for driver in drivers)
    assert "CONVENTION" in result["honesty_label"]
    assert result["assumptions"]["sweep_method"].startswith("one driver")


def test_top_three_carry_requested_evidence_strings():
    result = tornado(
        _deal(),
        {"rent": 0.10, "exit_cap": 0.01, "opex": 0.10},
    )
    evidence = {
        item["driver"]: item["evidence_that_would_change_this"]
        for item in result["top_3"]
    }

    assert evidence["rent"] == "lease comps + executed-lease audit"
    assert evidence["exit_cap"] == "recent sale comps, debt-market direction"
    assert evidence["opex"] == "T12 vs GL, tax reassessment check"


def test_missing_exit_cap_leaves_irr_sensitivity_uncomputed():
    deal = _deal()
    del deal["exit_cap"]
    result = tornado(deal, {"rent": 0.10})
    driver = result["ranked_drivers"][0]

    assert result["base_case"]["irr"] is None
    assert driver["delta_irr"] is None
    assert driver["delta_dscr"] is not None
