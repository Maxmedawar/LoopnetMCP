from __future__ import annotations

import pytest

from cre_mcp.leasing.opening import opening_critical_path
from cre_mcp.leasing.proposals import compare_lease_proposals
from cre_mcp.leasing.prospects import tenant_prospect_list
from cre_mcp.leasing.watch import record_tenant_signal, tenant_watch_report


def test_proposal_effective_rent_and_npv_match_explicit_monthly_math() -> None:
    annual_discount = 0.12
    result = compare_lease_proposals(
        [
            {
                "tenant": "Crafted Tenant",
                "rent_psf": 24,
                "term_years": 1,
                "escalations": None,
                "ti_psf": 2,
                "free_rent_months": 1,
                "credit": {"type": "corporate", "guaranty": True},
                "contingencies": [],
            }
        ],
        {"sf": 1_000},
        annual_discount,
    )
    proposal = result["proposals"][0]

    # $2,000/month, one waived month, less $2,000 TI at month zero.
    assert proposal["collected_rent_total"] == 22_000
    assert proposal["net_undiscounted_cash_flow"] == 20_000
    assert proposal["effective_rent_psf"] == 20
    assert proposal["effective_rent"]["bridge"] == {
        "gross_average_rent_psf": 24,
        "less_free_rent_psf_per_year": 2,
        "less_ti_amortization_psf_per_year": 2,
    }

    monthly_discount = (1 + annual_discount) ** (1 / 12) - 1
    expected_npv = sum(
        2_000 / (1 + monthly_discount) ** month for month in range(2, 13)
    ) - 2_000
    assert proposal["net_npv"] == pytest.approx(round(expected_npv, 2))
    assert proposal["cash_flows"]["monthly"][0] == -2_000
    assert proposal["cash_flows"]["monthly"][1] == 0
    assert "not a probabilistic" in proposal["npv_range"]["label"]


def test_proposal_rankings_flip_by_objective_and_ti_changes_economic_order() -> None:
    result = compare_lease_proposals(
        [
            {
                "tenant": "Corporate High Headline",
                "rent_psf": 30,
                "term_years": 1,
                "escalations": 0,
                "ti_psf": 10,
                "free_rent_months": 0,
                "credit": {"type": "corporate", "guaranty": True},
                "contingencies": [],
            },
            {
                "tenant": "Local Low Headline",
                "rent_psf": 25,
                "term_years": 1,
                "escalations": 0,
                "ti_psf": 0,
                "free_rent_months": 0,
                "credit": {"type": "local", "guaranty": False},
                "contingencies": [],
            },
        ],
        {"sf": 1_000},
        0,
    )

    by_tenant = {row["tenant"]: row for row in result["proposals"]}
    assert by_tenant["Corporate High Headline"]["net_npv"] == 20_000
    assert by_tenant["Local Low Headline"]["net_npv"] == 25_000
    assert result["rankings"]["max_npv"][0]["tenant"] == "Local Low Headline"
    assert result["rankings"]["max_credit"][0]["tenant"] == "Corporate High Headline"
    assert result["rankings"]["min_downtime"][0]["tenant"] == "Corporate High Headline"
    assert "does not select a single winner" in result["objective_note"]


def test_opening_critical_path_quotes_trigger_and_exposes_slack() -> None:
    trigger = "  The earlier of opening or 180 days after delivery  "
    result = opening_critical_path(
        {
            "execution": "2026-01-01",
            "permits_est_days": 10,
            "ti_buildout_est_days": 20,
            "fixturing_days": 5,
            "target_open": "2026-02-10",
            "rent_commencement_date": "2026-02-20",
            "rent_commencement_trigger": trigger,
        },
        jurisdiction_note="Illustrative city review; confirm with the AHJ.",
    )

    assert result["chain_order"] == [
        "execution",
        "permit",
        "ti_buildout",
        "fixturing",
        "open",
        "rent_commencement",
    ]
    assert result["permit_complete_date"] == "2026-01-11"
    assert result["ti_complete_date"] == "2026-01-31"
    assert result["fixturing_complete_date"] == "2026-02-05"
    assert result["projected_open_date"] == "2026-02-05"
    assert result["projected_rent_commencement_date"] == "2026-02-20"
    assert result["slack_days"] == {
        "to_target_open": 5,
        "from_projected_open_to_rent_commencement": 15,
    }
    assert result["quoted_rent_commencement_trigger"] == trigger
    assert "not interpreted" in result["assumptions"]["legal_limitation"]
    permit_risk = next(
        risk for risk in result["risk_points"] if risk["stage"] == "permit"
    )
    assert "jurisdiction-dependent" in permit_risk["risk"]
    assert permit_risk["status"] == "flag"


def test_watch_lifecycle_is_chronological_and_cautiously_framed(tmp_path) -> None:
    db_path = tmp_path / "leasing-watch.db"
    later = record_tenant_signal(
        "Example Tenant",
        "coffee",
        "credit_downgrade",
        "high",
        "Analyst-entered downgrade signal",
        "2026-02-02T10:00:00Z",
        db_path=db_path,
    )
    earlier = record_tenant_signal(
        "Example Tenant",
        "coffee",
        "manual_note",
        "info",
        "Lease conversation noted by broker",
        "2026-01-01",
        db_path=db_path,
    )

    assert later["signal_label"] == "structured input; not independently verified"
    assert earlier["signal_type"] == "manual_note"

    report = tenant_watch_report("example tenant", db_path=db_path)
    assert report["signal_count"] == 2
    assert [signal["signal_type"] for signal in report["signals"]] == [
        "manual_note",
        "credit_downgrade",
    ]
    assert report["renewal_risk_framing"]["label"] == "elevated_review"
    assert "not a credit opinion" in report["renewal_risk_framing"]["limitations"]
    assert report["automated_feeds"]["status"] == "later_phase"
    assert report["automated_feeds"]["included_now"] is False


def test_prospect_list_is_catalog_limited_and_never_promises_a_signature(
    tmp_path,
) -> None:
    result = tenant_prospect_list(
        {
            "sf": 2_500,
            "frontage": 110,
            "demographics": {
                "population": 55_000,
                "median_income": 80_000,
                "traffic_aadt": 30_000,
            },
            "watch_db_path": tmp_path / "prospect-watch.db",
        },
        existing_cotenancy=[
            {"brand": "Starbucks", "category": "coffee", "distance_m": 750}
        ],
    )

    assert result["catalog_count"] == 30
    assert len(result["prospects"]) == result["catalog_count"]
    coverage = result["catalog_coverage_note"].casefold()
    assert "30" in coverage
    assert "not the universe" in coverage

    by_brand = {prospect["brand"]: prospect for prospect in result["prospects"]}
    starbucks = by_brand["Starbucks"]
    assert starbucks["whitespace_status"] == "same_brand_present"
    assert "cannibalization" in starbucks["whitespace_note"].casefold()

    unseen = next(
        prospect
        for brand, prospect in by_brand.items()
        if brand != "Starbucks"
    )
    assert unseen["whitespace_status"] == "not_observed_in_inputs"
    assert "not proof" in unseen["whitespace_note"].casefold()
    assert all(
        "no assertion" in prospect["pursuit_disclaimer"].casefold()
        and "sign" in prospect["pursuit_disclaimer"].casefold()
        for prospect in result["prospects"]
    )
