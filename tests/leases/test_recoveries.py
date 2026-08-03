"""Real-lease recovery extraction and hand-checked billing math."""

from pathlib import Path

import pytest

from cre_mcp.leases.models import CitedClaim
from cre_mcp.leases.reader import read_lease
from cre_mcp.leases.recoveries import (
    CAMCap,
    ProRataShare,
    RecoveryTerms,
    estimate_recoverable,
    extract_recovery_terms,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "leases"


def _claim(value):
    return CitedClaim.stated(value, quote=str(value), locator="Synthetic", confidence=1.0)


def test_acpt_base_year_tax_and_cam_terms_are_cited_from_real_lease():
    document = read_lease(FIXTURES / "retail_lease_acpt.htm")

    terms = extract_recovery_terms(document)

    assert terms.cam_recovery.value == "pro_rata"
    assert terms.tax_recovery.value == "base_year_stop"
    assert terms.base_year.value == "2005-2006"
    assert terms.pro_rata_share.formula.value == "tenant_sf / total_sf"
    for claim in (
        terms.cam_recovery,
        terms.tax_recovery,
        terms.base_year,
        terms.pro_rata_share.formula,
    ):
        assert claim.status in {"stated", "inferred"}
        assert claim.quote in document.text
        assert claim.locator


def test_community_bancorp_cam_exclusions_audit_and_honest_misses():
    document = read_lease(FIXTURES / "retail_lease_community_bancorp.htm")

    terms = extract_recovery_terms(document.text)

    assert terms.cam_recovery.value == "pro_rata"
    assert terms.tax_recovery.value == "pro_rata"
    assert terms.insurance_recovery.value == "included_in_cam"
    assert terms.pro_rata_share.formula.value == "tenant_sf / total_sf"
    assert terms.audit_right.right.value is True
    assert terms.audit_right.window_months.value == 12
    categories = {claim.value["category"] for claim in terms.exclusions}
    assert {"capital_expenditures", "debt_service", "earthquake_flood_insurance"} <= categories
    # The lease has no CAM cap/gross-up, and its unrelated $350 estoppel
    # administrative charge must not be mistaken for a CAM administration fee.
    assert terms.cam_cap.pct.status == "missing"
    assert terms.gross_up_pct.status == "missing"
    assert terms.admin_fee_pct.status == "missing"
    for claim in terms.exclusions:
        assert claim.quote in document.text


def test_dollar_tree_alternative_cam_charge_wording_is_generic_and_cited():
    document = read_lease(FIXTURES / "retail_lease_dollar_tree.htm")

    terms = extract_recovery_terms(document)

    assert terms.cam_recovery.value == "pro_rata"
    assert terms.insurance_recovery.value == "included_in_cam"
    assert terms.pro_rata_share.formula.value == "tenant_sf / total_sf"
    assert terms.cam_cap.pct.value == 0.15
    assert terms.cam_cap.over_base_vs_yoy.value == "yoy"
    assert terms.cam_cap.cumulative_vs_noncumulative.status == "missing"
    assert terms.admin_fee_pct.value == 0.15
    for claim in (
        terms.cam_recovery,
        terms.insurance_recovery,
        terms.pro_rata_share.formula,
        terms.cam_cap.pct,
        terms.admin_fee_pct,
    ):
        assert claim.quote in document.text


def test_recovery_silence_is_missing_not_a_recovery_default():
    terms = extract_recovery_terms("Tenant leases Suite 2 for a five-year term.")

    assert terms.method.status == "missing"
    assert terms.cam_recovery.status == "missing"
    assert terms.tax_recovery.status == "missing"
    assert terms.insurance_recovery.status == "missing"
    assert terms.pro_rata_share.stated_pct.status == "missing"


def test_estimate_recoverable_applies_share_binding_cap_and_admin_fee():
    terms = RecoveryTerms(
        cam_recovery=_claim("pro_rata"),
        cam_cap=CAMCap(
            pct=_claim(0.05),
            cumulative_vs_noncumulative=_claim("noncumulative"),
            over_base_vs_yoy=_claim("yoy"),
        ),
        admin_fee_pct=_claim(0.10),
        pro_rata_share=ProRataShare(stated_pct=_claim(0.10)),
        tax_recovery=_claim("pro_rata"),
        insurance_recovery=_claim("pro_rata"),
    )

    result = estimate_recoverable(
        terms,
        {
            "cam": {"current": 120_000, "prior": 100_000},
            "taxes": 50_000,
            "insurance": 20_000,
        },
        tenant_sf=10_000,
        total_sf=100_000,
    )

    assert result["lines"]["cam"]["eligible_cost"] == 105_000
    assert result["lines"]["cam"]["admin_fee"] == 1_050
    assert result["lines"]["cam"]["estimated_billing"] == 11_550
    assert result["lines"]["taxes"]["estimated_billing"] == 5_000
    assert result["lines"]["insurance"]["estimated_billing"] == 2_000
    assert result["total_estimated_billing"] == 18_550


def test_estimate_derives_share_from_supplied_geometry_with_review_flag():
    terms = RecoveryTerms(
        cam_recovery=_claim("pro_rata"),
        admin_fee_pct=_claim(0.10),
    )

    result = estimate_recoverable(
        terms,
        {"cam": 100_000},
        tenant_sf=10_000,
        total_sf=100_000,
    )

    assert result["pro_rata_share"] == 0.10
    assert result["pro_rata_share_status"] == "inferred"
    assert result["pro_rata_share_basis"] == [
        "derived from tenant_sf/total_sf (lease states no percentage)"
    ]
    assert result["lines"]["cam"]["estimated_billing"] == 11_000
    assert result["lines"]["cam"]["admin_fee"] == 1_000
    assert any(
        "GLA vs GLA-occupied vs defined Center" in flag["issue"]
        for flag in result["professional_review_flags"]
    )


def test_common_proportionate_share_percentage_phrasing_family():
    phrases = (
        "Tenant shall pay Tenant's Proportionate Share (10%) of Common Area Maintenance costs.",
        "Tenant's Proportionate Share shall be ten percent (10%).",
        "Proportionate Share shall equal 10 percent (10%).",
        "Tenant's Percentage Share is 10%.",
    )

    for phrase in phrases:
        terms = extract_recovery_terms(phrase)

        assert terms.pro_rata_share.stated_pct.status == "stated"
        assert terms.pro_rata_share.stated_pct.value == 0.10
        assert terms.pro_rata_share.stated_pct.quote in phrase


def test_admin_fee_of_written_percentage_extracts_and_bills_exactly():
    text = (
        "Tenant shall pay Tenant's Proportionate Share (10%) of Common Area "
        "Maintenance costs plus an administrative fee of fifteen percent (15%) "
        "of CAM costs."
    )

    terms = extract_recovery_terms(text)
    result = estimate_recoverable(
        terms,
        {"cam": 200_000},
        tenant_sf=None,
        total_sf=None,
    )

    assert terms.admin_fee_pct.status == "stated"
    assert terms.admin_fee_pct.value == 0.15
    assert terms.admin_fee_pct.quote in text
    assert result["lines"]["cam"]["admin_fee"] == 3_000
    assert result["lines"]["cam"]["estimated_billing"] == 23_000


def test_admin_fee_connector_family_and_maximum_review_flag():
    phrasings = (
        "administrative fee of 15% of CAM costs",
        "administrative fee in the amount of fifteen percent (15%) of Common Area Maintenance costs",
        "administrative fee not to exceed fifteen percent (15%) of CAM costs",
    )

    for phrasing in phrasings:
        terms = extract_recovery_terms(f"Tenant shall pay CAM costs plus an {phrasing}.")
        assert terms.admin_fee_pct.value == 0.15

    maximum = extract_recovery_terms(
        "Tenant shall pay Tenant's Proportionate Share (10%) of CAM costs plus an "
        "administrative fee not to exceed fifteen percent (15%) of CAM costs."
    )
    result = estimate_recoverable(maximum, {"cam": 200_000}, None, None)

    assert any("stated as maximum" in flag["issue"] for flag in maximum.professional_review_flags)
    assert any("stated as maximum" in flag["issue"] for flag in result["professional_review_flags"])
    assert any("cited maximum" in basis for basis in result["lines"]["cam"]["basis"])


def test_cumulative_and_noncumulative_cam_caps_use_different_bases():
    common = {
        "cam_recovery": _claim("pro_rata"),
        "pro_rata_share": ProRataShare(stated_pct=_claim(0.10)),
    }
    cumulative = RecoveryTerms(
        **common,
        cam_cap=CAMCap(
            pct=_claim(0.05),
            cumulative_vs_noncumulative=_claim("cumulative"),
            over_base_vs_yoy=_claim("over_base"),
        ),
    )
    noncumulative = RecoveryTerms(
        **common,
        cam_cap=CAMCap(
            pct=_claim(0.05),
            cumulative_vs_noncumulative=_claim("noncumulative"),
            over_base_vs_yoy=_claim("yoy"),
        ),
    )
    costs = {"cam": {"current": 130_000, "base": 100_000, "prior": 110_000, "years_elapsed": 2}}

    cumulative_result = estimate_recoverable(cumulative, costs, None, None)
    noncumulative_result = estimate_recoverable(noncumulative, costs, None, None)

    assert cumulative_result["lines"]["cam"]["eligible_cost"] == pytest.approx(110_250)
    assert noncumulative_result["lines"]["cam"]["eligible_cost"] == pytest.approx(115_500)
    assert cumulative_result["lines"]["cam"]["estimated_billing"] == pytest.approx(11_025)
    assert noncumulative_result["lines"]["cam"]["estimated_billing"] == pytest.approx(11_550)


def test_missing_cap_mechanics_are_flagged_not_silently_assumed():
    terms = RecoveryTerms(
        cam_recovery=_claim("pro_rata"),
        cam_cap=CAMCap(pct=_claim(0.05)),
        pro_rata_share=ProRataShare(stated_pct=_claim(0.10)),
    )

    result = estimate_recoverable(terms, {"cam": 100_000}, None, None)

    assert result["lines"]["cam"]["status"] == "not_computable"
    assert "unambiguous_cam_cap_mechanics" in result["lines"]["cam"]["missing_inputs"]
    assert any("ambiguous" in flag["issue"] for flag in result["professional_review_flags"])


def test_gross_up_applies_only_with_occupancy_and_variable_cost_basis():
    terms = RecoveryTerms(
        cam_recovery=_claim("pro_rata"),
        gross_up_pct=_claim(0.95),
        pro_rata_share=ProRataShare(stated_pct=_claim(0.10)),
    )

    result = estimate_recoverable(
        terms,
        {"cam": {"current": 80_000, "variable": 50_000, "occupancy_pct": 0.50}},
        None,
        None,
    )
    missing_basis = estimate_recoverable(terms, {"cam": 80_000}, None, None)

    assert result["lines"]["cam"]["eligible_cost"] == 125_000
    assert result["lines"]["cam"]["estimated_billing"] == 12_500
    assert missing_basis["lines"]["cam"]["status"] == "not_computable"
    assert "annual_costs.cam.occupancy_pct" in missing_basis["lines"]["cam"]["missing_inputs"]
