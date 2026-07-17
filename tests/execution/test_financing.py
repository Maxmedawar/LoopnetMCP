"""Asset-specific lender-type eligibility, ranking, and rate anchoring."""

import pytest

from cre_mcp.execution.financing import financing_options
from cre_mcp.models import ListingFacts
from tests.scoring.builders import deal_context, market_pack


def _by_type(ctx):
    return {option.type: option for option in financing_options(ctx)}


def test_nnn_investment_explicitly_excludes_sba_owner_occupied_debt():
    ctx = deal_context(
        property_type="retail",
        price=2_500_000,
        noi=175_000,
        raw={
            "strategy": "nnn_retail",
            "lease_type": "absolute NNN",
            "owner_occupied": False,
        },
        market=market_pack({"treasury_10yr": 4.5, "sofr": 4.35}),
    )
    ctx.facts = ListingFacts(strategy_hint="nnn_retail", nnn_purity="absolute")

    options = financing_options(ctx)
    by_type = {option.type: option for option in options}

    assert by_type["sba_504_7a"].eligible is False
    assert by_type["sba_504_7a"].fit == "not_eligible"
    assert "passive NNN" in by_type["sba_504_7a"].why_or_why_not
    assert options[0].type == "cmbs_conduit"
    assert options[0].typical_rate == pytest.approx(6.75)
    assert "treasury_10yr" in options[0].rate_basis
    assert "225 bps" in options[0].rate_basis
    assert all("not a loan commitment" in option.guardrail for option in options)


def test_stabilized_five_plus_unit_multifamily_ranks_agency_first():
    ctx = deal_context(
        property_type="multifamily",
        price=4_000_000,
        units=24,
        noi=280_000,
        raw={"occupancy_rate": 0.94, "strategy": "core"},
        market=market_pack({"treasury_10yr": 4.0, "sofr": 4.2}),
    )

    options = financing_options(ctx)
    agency = _by_type(ctx)["agency_multifamily"]

    assert options[0].type == "agency_multifamily"
    assert agency.eligible is True
    assert agency.fit == "strong"
    assert "24-unit" in agency.why_or_why_not


def test_value_add_multifamily_routes_to_bridge_not_stabilized_agency():
    ctx = deal_context(
        property_type="multifamily",
        price=3_000_000,
        units=20,
        noi=120_000,
        raw={"strategy": "value_add_multifamily", "business_plan": "lease-up renovation"},
    )
    by_type = _by_type(ctx)

    assert by_type["bridge_debt_fund"].eligible is True
    assert by_type["agency_multifamily"].eligible is False
    assert "transitional" in by_type["agency_multifamily"].why_or_why_not


def test_documented_owner_occupied_asset_can_clear_initial_sba_screen():
    ctx = deal_context(
        property_type="industrial",
        price=1_500_000,
        noi=130_000,
        raw={"owner_occupancy_pct": 60, "business_plan": "operating business facility"},
    )
    sba = _by_type(ctx)["sba_504_7a"]

    assert sba.eligible is True
    assert "60.0%" in sba.why_or_why_not


def test_passive_investment_label_cannot_override_sba_rule_with_bad_owner_flag():
    ctx = deal_context(
        property_type="retail",
        price=1_500_000,
        noi=100_000,
        raw={"owner_occupied": True, "investment_type": "passive investment property"},
    )
    sba = _by_type(ctx)["sba_504_7a"]
    assert sba.eligible is False
    assert "investment property" in sba.why_or_why_not
