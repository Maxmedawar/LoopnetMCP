from __future__ import annotations

from cre_mcp.mlops.option_pricing import price_control_option
from cre_mcp.mlops.scenarios import CONTROL_EVENTS, control_scenarios


def test_subtenant_default_exposure_range_includes_operating_expense():
    result = control_scenarios(
        {
            "master_rent_owed_cents": 500_000,
            "sublease_billed_cents": 700_000,
            "sublease_received_cents": 300_000,
            "expense_cents": 100_000,
            "remaining_term_months": 6,
            "reserves_cents": 200_000,
            "security_cents": 50_000,
        },
        [
            {
                "event": "subtenant_default",
                "clause_text": (
                    "Section 18: after required notice and cure, landlord may pursue "
                    "the remedies stated in this sublease."
                ),
            }
        ],
    )

    scenario = result["scenarios"][0]
    assert next(iter(result)) == "rent_owed_vs_received_exposure"
    assert result["rent_owed_vs_received_exposure"]["monthly_negative_carry_cents"] == 300_000
    assert scenario["cash_exposure_range_cents"] == {
        "low": 900_000,
        "high": 3_600_000,
    }
    assert scenario["unfunded_after_reserves_range_cents"] == {
        "low": 700_000,
        "high": 3_400_000,
    }
    assert scenario["clause_citation"]["quote"].startswith("Section 18")
    assert scenario["counsel_flag"] is True


def test_every_control_event_has_a_range_checklist_and_mitigation():
    result = control_scenarios(
        {
            "master_rent_cents": 100_000,
            "sublease_received_cents": 90_000,
            "remaining_term_months": 24,
        },
        tuple(CONTROL_EVENTS),
    )

    assert result["events_modeled"] == list(CONTROL_EVENTS)
    for scenario in result["scenarios"]:
        exposure = scenario["cash_exposure_range_cents"]
        assert 0 <= exposure["low"] <= exposure["high"]
        assert scenario["rights_remedies_checklist"]
        assert scenario["rights_remedies_checklist"][0]["status"] == "missing_source"
        assert scenario["mitigation_options"]
        assert scenario["counsel_flag"] is True


def test_option_intrinsic_and_flat_window_math_are_penny_exact():
    result = price_control_option(
        {
            "strike_cents": 1_000_000,
            "exercisable_from": "2027-01-01",
            "exercisable_until": "2028-01-01",
            "extension_terms": [{"months": 12, "strike_step_up_pct": "5"}],
        },
        {
            "value_range_now_cents": [900_000, 1_300_000],
            "growth_scenarios": {"flat": "0"},
            "as_of": "2026-01-01",
        },
        {
            "master_rent_owed_cents": 500_000,
            "sublease_received_cents": 450_000,
            "expense_cents": 25_000,
        },
    )

    assert next(iter(result)) == "rent_owed_vs_received_exposure"
    assert result["intrinsic_value_range_now_cents"] == {
        "low": 0,
        "high": 300_000,
    }
    scenario = result["scenario_values"][0]
    assert scenario["at_exercisable_from"]["intrinsic_value_range_cents"] == {
        "low": 0,
        "high": 300_000,
    }
    assert scenario["at_exercisable_until"]["intrinsic_value_range_cents"] == {
        "low": 0,
        "high": 300_000,
    }
    assert result["rent_owed_vs_received_exposure"]["monthly_negative_carry_cents"] == 75_000
    assert result["assumptions"]["extension_value_modeled"] is False
    assert "not independently priced" in result["control_premium_note"]
