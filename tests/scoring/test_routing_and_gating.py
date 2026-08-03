"""Extracted-fact routing and honest low-evidence grade gating."""

from cre_mcp.enrichment.listing_facts import extract_facts
from cre_mcp.models import DealContext, Listing
from cre_mcp.scoring.engine import score, score_all
from cre_mcp.scoring.rubrics import NNN_RETAIL_RUBRIC, applicable_rubrics
from cre_mcp.underwriting.metrics import underwrite_listing
from tests.scoring.builders import deal_context, market_pack


def _austin_nnn() -> DealContext:
    listing = Listing(
        source="fixture",
        source_id="austin-nnn-regression",
        name="Brand-New 16-Year Absolute NNN Lease",
        address="100 Congress Ave",
        city="Austin",
        state="TX",
        property_type="Retail",
        description="Single-tenant offering with 1.5% annual increases.",
        price_usd=1_500_000,
        noi_usd=90_000,
        url="https://example.test/austin-nnn-regression",
    )
    return DealContext(
        listing=listing,
        facts=extract_facts(listing),
        underwriting=underwrite_listing(listing),
    )


def test_austin_nnn_blurb_routes_and_credits_extracted_lease_signals():
    ctx = _austin_nnn()

    assert [rubric.strategy for rubric in applicable_rubrics(ctx)] == ["nnn_retail"]
    result = score_all(ctx)[0]
    signals = {
        item.key: item for item in result.rubric_result.signal_results
    }

    assert result.strategy == "nnn_retail"
    assert signals["lease_years_remaining"].raw_value == 16.0
    assert signals["lease_years_remaining"].missing is False
    assert signals["rent_escalations"].missing is False
    assert signals["nnn_purity"].raw_value == 1.0


def test_thin_nnn_keeps_numeric_score_but_returns_nr_not_f():
    result = score_all(_austin_nnn())[0]

    assert result.score > 0
    assert result.grade == "NR"
    assert result.gated is True
    assert result.explanation.startswith("Not rated — insufficient data to score.")
    assert "Biggest missing inputs:" in result.explanation
    assert "Get them by:" in result.explanation


def test_known_tenant_and_guaranty_facts_feed_existing_credit_signals():
    ctx = _austin_nnn()
    listing = ctx.listing.model_copy(
        update={
            "name": "7-Eleven | Brand-New 16-Year Absolute NNN Lease",
            "description": (
                "Single-tenant offering with 1.5% annual increases and a "
                "corporate guaranty."
            ),
        }
    )
    ctx = ctx.model_copy(
        update={"listing": listing, "facts": extract_facts(listing)}
    )

    result = score(ctx, NNN_RETAIL_RUBRIC)
    signals = {
        item.key: item for item in result.rubric_result.signal_results
    }

    assert signals["tenant_credit_tier"].raw_value == 0.9
    assert signals["corporate_vs_franchisee"].raw_value == 0.7


def test_well_covered_deal_keeps_ordinary_grade_and_is_ungated():
    ctx = deal_context(
        raw={
            "tenant_credit_rating": "A",
            "lease_years_remaining": 16,
            "rent_escalation_pct": 3,
            "lease_type": "absolute nnn",
            "guaranty_type": "corporate investment grade",
            "traffic_count": 35_000,
            "population_3mi": 80_000,
            "median_income_3mi": 100_000,
            "visibility": "corner drive-thru",
            "replacement_cost_per_sf": 400,
            "credit_anchors": 4,
        },
        market=market_pack(
            {
                "job_growth_5yr": 3.0,
                "pop_growth_5yr": 2.0,
                "median_hh_income": 100_000,
                "treasury_10yr": 4.0,
            }
        ),
    )

    result = score(ctx, NNN_RETAIL_RUBRIC)

    assert result.rubric_result.coverage >= 0.5
    assert result.confidence >= 0.5
    assert result.grade != "NR"
    assert result.gated is False
    assert not result.explanation.startswith("Not rated")
