"""Evidence-honesty tests for VE, percent complete, and closeout."""

from __future__ import annotations

from cre_mcp.construction.closeout import closeout_register
from cre_mcp.construction.ve_percent import percent_complete, ve_option


def test_ve_savings_that_destroy_noi_destroy_value_at_exit():
    result = ve_option(
        {
            "desc": "Delete lobby amenity",
            "capex_delta_cents": -20_000_000,
            "noi_delta_cents": -3_000_000,
            "life_effect": "shorter tenant-facing finish life",
        },
        exit_cap=0.05,
    )

    assert "error" not in result
    # $200k saved is outweighed by $30k NOI loss / 5% = $600k value loss.
    assert result["noi_value_delta_cents"] == -60_000_000
    assert result["capex_value_effect_cents"] == 20_000_000
    assert result["net_value_delta_cents"] == -40_000_000
    assert result["value_destruction"] is True
    assert "destruction" in result["classification"].casefold()
    assert all(figure["basis_tag"] for figure in result["figures"])
    assert all(
        result["review_flags"][key] is True
        for key in (
            "gc_review_required",
            "architect_review_required",
            "inspector_review_required",
        )
    )


def test_percent_complete_never_promotes_invoices_to_field_verification():
    result = percent_complete(
        {
            "invoiced_cents": 600_000,
            "budget_cents": 1_000_000,
            "inspection_pct": 40,
            "schedule_pct": 55,
        }
    )

    assert "error" not in result
    assert result["invoice_supported_pct"] == 60
    assert result["field_verified_pct"] == 40
    assert result["schedule_reported_pct"] == 55
    assert result["divergence_pct_points"] == 20
    assert result["divergence_flag"] is True
    assert set(result["views"]) == {
        "invoice_supported",
        "field_verified",
        "schedule_reported",
    }
    assert "invoice" in result["basis_tags"]["invoice_supported"].casefold()
    assert "field" in result["basis_tags"]["field_verified"].casefold()
    assert "schedule" in result["basis_tags"]["schedule_reported"].casefold()
    assert (
        result["views"]["invoice_supported"]["basis"]
        != result["views"]["field_verified"]["basis"]
    )
    assert all(
        result["review_flags"][key] is True
        for key in (
            "gc_review_required",
            "architect_review_required",
            "inspector_review_required",
        )
    )


def test_percent_complete_keeps_nullable_evidence_absent_not_zero_or_verified():
    result = percent_complete(
        {
            "invoiced_cents": 250_000,
            "budget_cents": 1_000_000,
            "inspection_pct": None,
            "schedule_pct": None,
        }
    )

    assert "error" not in result
    assert result["invoice_supported_pct"] == 25
    assert result["field_verified_pct"] is None
    assert result["schedule_reported_pct"] is None
    assert result["views"]["field_verified"]["pct"] is None
    assert result["views"]["schedule_reported"]["pct"] is None


def test_closeout_reports_document_gaps_and_hands_off_received_warranties():
    result = closeout_register(
        [
            {
                "type": "warranty",
                "item": "roof membrane",
                "received": True,
                "expires": "2036-07-01",
            },
            {
                "type": "as_built",
                "item": "electrical as-builts",
                "received": False,
            },
            {
                "type": "o_and_m",
                "item": "HVAC O&M manuals",
                "received": True,
            },
            {
                "type": "permit_final",
                "item": "final certificate of occupancy",
                "received": False,
            },
        ]
    )

    assert "error" not in result
    assert result["closeout_complete"] is False
    assert any("electrical as-builts" in str(gap) for gap in result["gaps"])
    assert any("certificate of occupancy" in str(gap) for gap in result["gaps"])
    assert "lien_release" in result["missing_required_types"]
    assert len(result["warranty_calendar_handoff"]) == 1
    warranty = result["warranty_calendar_handoff"][0]
    assert warranty["item"] == "roof membrane"
    assert warranty["expires"] == "2036-07-01"
    assert all(
        result["review_flags"][key] is True
        for key in (
            "gc_review_required",
            "architect_review_required",
            "inspector_review_required",
        )
    )


def test_received_warranty_without_expiration_is_not_ready_for_handoff():
    result = closeout_register(
        [{"type": "warranty", "item": "elevator controls", "received": True}]
    )

    assert "error" not in result
    assert any(
        "elevator controls" in str(item)
        for item in result["warranties_missing_expiration"]
    )
    assert result["closeout_complete"] is False
