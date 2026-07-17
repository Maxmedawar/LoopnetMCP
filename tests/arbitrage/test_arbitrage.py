"""Pure tests for Phase 32 master-lease arbitrage."""

from __future__ import annotations

import asyncio

import pytest

from cre_mcp.arbitrage.economics import master_lease_arbitrage
from cre_mcp.arbitrage.finder import find_arbitrage_opportunities
from cre_mcp.arbitrage.proposals import draft_subtenant_outreach
from cre_mcp.tools.arbitrage_tools import master_lease_playbook


def test_master_lease_economics_exact_math_and_negative_carry() -> None:
    result = master_lease_arbitrage(
        master_rent_annual=60_000,
        building_sqft=2_000,
        sublease_rent_psf=45,
        sublease_occupancy=0.95,
    )

    assert result["gross_sublease_income"] == 85_500
    assert result["variable_cost"] == 4_275
    assert result["fixed_cost"] == 60_000
    assert result["total_cost"] == 64_275
    assert result["net_cash_flow_annual"] == 21_225
    assert result["rent_coverage"] == 1.425
    assert result["breakeven_occupancy"] == pytest.approx(2 / 3)
    assert result["negative_carry_exposure_annual"] == 60_000
    assert "negative_carry" in result["risk_flags"]
    assert result["projection"][0]["net"] == 21_225


def test_thin_coverage_is_flagged() -> None:
    result = master_lease_arbitrage(
        master_rent_annual=80_000,
        building_sqft=2_000,
        sublease_rent_psf=45,
    )

    assert result["rent_coverage"] < 1.25
    assert "thin_coverage" in result["risk_flags"]


def test_finder_ranks_positive_spreads_and_counts_filtered_deals() -> None:
    results = find_arbitrage_opportunities(
        [
            {
                "id": "middle",
                "master_rent_annual": 60_000,
                "building_sqft": 2_000,
            },
            {
                "id": "best",
                "asking_rent_psf": 20,
                "building_sqft": 2_000,
            },
            {
                "id": "negative",
                "master_rent_annual": 90_000,
                "building_sqft": 2_000,
            },
            {"id": "missing-size", "master_rent_annual": 40_000},
        ],
        achievable_sublease_psf=45,
    )

    assert [result["id"] for result in results] == ["best", "middle"]
    assert all(result["economics"]["net_cash_flow_annual"] > 0 for result in results)
    summary = results[0]["screening_summary"]
    assert summary["filtered_non_positive_count"] == 1
    assert summary["skipped_missing_or_invalid_count"] == 1
    assert "building_sqft" in summary["skipped_spaces"][0]["reason"]


def test_subtenant_outreach_weaves_in_all_provided_selling_points() -> None:
    outreach = draft_subtenant_outreach(
        tenant_name="Example Coffee",
        address="100 Main Street",
        building_sqft=2_200,
        sublease_rent_psf=42,
        term_years=7,
        aadt=32_000,
        foot_traffic_daily=1_400,
        parking_spaces=40,
        amenities=["patio", "pylon signage"],
        nearby_anchors=["Whole Foods", "Orangetheory"],
        drive_thru=True,
    )

    body = outreach["body"]
    assert "32,000" in body
    assert "Whole Foods" in body
    assert "40 parking spaces" in body
    assert "$42.00/SF/year" in body
    assert "1,400" in body
    assert "patio" in body
    assert "drive-thru" in body


def test_master_lease_playbook_packages_every_section() -> None:
    playbook = asyncio.run(
        master_lease_playbook(
            {
                "id": "candidate-1",
                "address": "200 Market Avenue",
                "master_rent_annual": 60_000,
                "building_sqft": 2_000,
                "achievable_sublease_psf": 45,
                "aadt": 30_000,
                "parking_spaces": 25,
                "has_drive_thru": True,
                "amenities": ["pylon signage"],
            },
            nearby_anchors=["Target"],
            top_n_tenants=3,
        )
    )

    assert set(playbook) == {
        "economics",
        "candidate_subtenants",
        "owner_proposal",
        "sample_outreach",
        "risk_flags",
    }
    assert len(playbook["candidate_subtenants"]) >= 1
    assert playbook["candidate_subtenants"][0]["guaranty_tier"] in {
        "corporate",
        "franchisee",
        "mixed",
    }
    assert "negative_carry" in playbook["risk_flags"]
