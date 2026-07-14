from cre_mcp.notes.strategies import compare_workouts
from cre_mcp.notes.tools import estimate_foreclosure_timeline


def _note_facts():
    return {
        "upb": 400_000,
        "rate": 0.065,
        "payment_history": {
            "status": "non",
            "months_delinquent": 8,
            "remaining_months": 120,
        },
        "collateral_value_range": (450_000, 600_000),
        "state": "TX",
        "lien_position": 1,
        "costs": {
            "foreclosure": 18_000,
            "legal": 10_000,
            "carry_monthly": 1_500,
            "receiver_cost": (5_000, 15_000),
        },
        "target_yield_range": (0.10, 0.14),
    }


def test_workout_comparison_has_all_seven_strategies_and_review_flags():
    result = compare_workouts(
        _note_facts(),
        {
            "cooperative": False,
            "liquidity_to_cure": False,
            "financials_available": False,
            "willing_to_convey_dil": False,
        },
    )

    assert {row["strategy"] for row in result["comparison_table"]} == {
        "cure_reinstate",
        "modification",
        "forbearance",
        "foreclosure",
        "deed_in_lieu",
        "note_sale",
        "receiver",
    }
    for row in result["comparison_table"]:
        assert set(row["expected_value"]) == {"low", "base", "high"}
        assert set(row["time_months"]) == {"low", "base", "high"}
        assert row["professional_review_required"] is True
        assert row["professional_review_flags"]
        assert row["what_borrower_must_agree"]


def test_plain_tool_wrapper_surfaces_assumptions_authority_and_counsel_gate():
    result = estimate_foreclosure_timeline("CA")

    assert result["tool_assumption_sheet"]
    assert result["authority"]["commit_funds_or_wire"].startswith("AI may NEVER")
    assert result["professional_review_required"] is True
    assert any("licensed foreclosure counsel" in flag for flag in result["professional_review_flags"])
