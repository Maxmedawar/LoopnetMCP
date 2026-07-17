"""Penny-exact draw forecasting and pay-app audit tests."""

from __future__ import annotations

import pytest

from cre_mcp.construction.draws import audit_pay_app, forecast_draws


@pytest.mark.parametrize("curve", ["linear", "s_curve"])
def test_draw_curve_allocates_every_cent_and_finishes_at_zero_cost_to_complete(curve):
    budget_cents = 10_000_001
    result = forecast_draws(
        {"total_cents": budget_cents},
        {"start": "2026-08-01", "months": 7, "curve": curve},
        {
            "annual_interest_rate": 0.06,
            "interest_reserve_cents": 100_000,
            "loan_to_cost_pct": 0.70,
        },
    )

    assert "error" not in result
    assert result["total_budget_cents"] == budget_cents
    assert len(result["monthly_draws"]) == 7
    assert sum(
        month["projected_draw_cents"] for month in result["monthly_draws"]
    ) == budget_cents
    assert result["monthly_draws"][-1]["cumulative_draw_cents"] == budget_cents
    assert result["monthly_draws"][-1]["remaining_cost_to_complete_cents"] == 0
    assert result["interest_reserve_check"]["required_interest_cents"] >= 0
    assert result["interest_reserve_check"]["status"] in {"adequate", "shortfall"}
    assert (
        result["interest_reserve_check"]["surplus_shortfall_cents"] >= 0
    ) == (result["interest_reserve_check"]["status"] == "adequate")
    flags = " ".join(result["professional_review_flags"]).casefold()
    assert all(role in flags for role in ("gc", "architect", "inspector"))


def test_pay_app_retainage_is_penny_exact_and_overbilling_respects_field_evidence():
    result = audit_pay_app(
        {
            "lines": [
                {
                    "item": "Concrete",
                    "scheduled_cents": 100_000,
                    "prev_billed_cents": 10_000,
                    "this_period_cents": 8_010,
                    "stored_materials_cents": 2_000,
                }
            ],
            "retainage_pct": 10,
        },
        {"inspection_pct": 15, "lien_waivers": []},
    )

    assert "error" not in result
    assert result["totals"]["current_gross_cents"] == 10_010
    assert result["totals"]["retainage_cents"] == 1_001
    assert result["totals"]["current_payment_due_cents"] == 9_009
    assert result["field_progress"]["pct"] == 15
    assert result["financial_progress"]["pct"] > result["field_progress"]["pct"]
    assert result["overbilling"]["flagged"] is True
    assert "Concrete" in str(result["missing_lien_waivers"])
    assert "Concrete" in str(result["stored_materials_flags"])
    assert "invoice" in result["financial_progress"]["basis"].casefold()
    assert "field" in result["field_progress"]["basis"].casefold()
    flags = " ".join(result["professional_review_flags"]).casefold()
    assert all(role in flags for role in ("gc", "architect", "inspector"))


def test_pay_app_with_received_waiver_does_not_report_it_missing():
    result = audit_pay_app(
        {
            "lines": [
                {
                    "item": "Steel",
                    "scheduled_cents": 500_000,
                    "prev_billed_cents": 0,
                    "this_period_cents": 50_000,
                    "stored_materials_cents": 0,
                }
            ],
            "retainage_pct": 5,
        },
        {
            "inspection_pct": None,
            "lien_waivers": [{"item": "Steel", "received": True}],
        },
    )

    assert "error" not in result
    assert result["missing_lien_waivers"] == []
    assert result["field_progress"]["pct"] is None
    assert result["overbilling"]["flagged"] is False
