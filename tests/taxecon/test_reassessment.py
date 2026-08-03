"""Property-tax reassessment rule and arithmetic tests."""

import pytest

from cre_mcp.taxecon.reassessment import STATE_RULES_REGISTRY, estimate_reassessment
from cre_mcp.taxecon.tools import estimate_tax_reassessment


def test_ca_prop_13_exact_purchase_price_and_millage_math():
    result = estimate_reassessment(
        purchase_price=2_000_000,
        current_assessed_value=1_000_000,
        current_annual_taxes=12_000,
        state="ca",
        county="Los Angeles",
    )

    assert result["state_rule"]["reassessment_on_sale"] == "full_reset_to_price"
    assert result["state_rule"]["annual_increase_cap_pct"] == 2.0
    assert result["projected_assessed_value"] == {
        "low": 2_000_000.0,
        "base": 2_000_000.0,
        "high": 2_000_000.0,
    }
    assert result["implied_millage"] == pytest.approx(0.012)
    assert result["projected_annual_taxes"]["base"] == 24_000
    assert result["annual_noi_delta"]["base"] == -12_000
    assert result["professional_review_required"] is True


def test_tx_has_no_price_based_sale_reset_and_warns_about_cad_reappraisal():
    result = estimate_reassessment(
        purchase_price=4_000_000,
        current_assessed_value=2_400_000,
        current_annual_taxes=54_000,
        state="TX",
        county="Dallas",
    )

    assert result["status"] == "NO_SALE_TRIGGER"
    assert result["state_rule"]["reassessment_on_sale"] == "periodic_reappraisal_no_sale_trigger"
    assert result["projected_assessed_value"]["base"] == 2_400_000
    assert result["projected_assessed_value"]["base"] != 4_000_000
    assert result["projected_annual_taxes"]["base"] == 54_000
    assert result["annual_noi_delta"]["base"] == 0
    warning = " ".join(result["caveats"] + list(result["method"].values())).casefold()
    assert "cad" in warning
    assert "not a forecast" in warning


def test_fl_nonhomestead_cap_resets_on_sale():
    result = estimate_reassessment(
        purchase_price=2_000_000,
        current_assessed_value=1_000_000,
        current_annual_taxes=15_000,
        state="FL",
    )

    assert result["state_rule"]["reassessment_on_sale"] == "cap_reset_on_sale"
    assert result["state_rule"]["annual_increase_cap_pct"] == 10.0
    assert result["projected_assessed_value"]["base"] == 2_000_000
    assert result["projected_annual_taxes"]["base"] == 30_000
    assert result["annual_noi_delta"]["base"] == -15_000
    assert "school" in result["state_rule"]["annual_increase_cap_scope"].casefold()


def test_unknown_state_returns_unknown_and_never_guesses():
    result = estimate_reassessment(1_000_000, 500_000, 8_000, "ID")

    assert result["status"] == "UNKNOWN"
    assert result["state_rule"]["reassessment_on_sale"] == "unknown"
    assert result["projected_assessed_value"]["base"] == "UNKNOWN"
    assert result["projected_annual_taxes"]["base"] == "UNKNOWN"
    assert "No value or tax rate was guessed" in result["caveats"][0]
    assert result["verify_with_county_assessor_or_tax_counsel_before_reliance"] is True


def test_millage_is_derived_from_current_record_not_silently_defaulted():
    result = estimate_tax_reassessment(
        purchase_price=1_500_000,
        current_assessed_value=800_000,
        current_annual_taxes=16_000,
        state="CA",
    )

    assert result["implied_millage"] == pytest.approx(0.02)
    assert result["projected_annual_taxes"]["base"] == 30_000
    assert "current annual taxes / current assessed value" in result["method"]["taxes"]
    assert result["assumption_sheet"]


def test_missing_purchase_price_uses_wider_labeled_asking_price_range():
    result = estimate_reassessment(
        purchase_price=None,
        current_assessed_value=500_000,
        current_annual_taxes=6_000,
        state="CA",
        asking_price=1_000_000,
    )

    assert result["projected_assessed_value"] == {
        "low": 900_000.0,
        "base": 1_000_000.0,
        "high": 1_100_000.0,
    }
    assert "asking price" in result["method"]["assessed_value"].casefold()
    assert "±10%" in result["method"]["assessed_value"]


def test_every_seeded_rule_has_source_confidence_and_verification_date():
    assert set(STATE_RULES_REGISTRY) == {
        "CA", "TX", "FL", "AZ", "NV", "CO", "GA", "NC", "TN", "OH", "IL", "NY", "WA", "VA"
    }
    for rule in STATE_RULES_REGISTRY.values():
        assert rule.source_citation
        assert rule.confidence in {"high", "medium", "low"}
        assert rule.last_verified == "2026-07"

