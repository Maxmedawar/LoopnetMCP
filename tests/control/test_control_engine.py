from cre_mcp.access.context import local_context, use_context
from cre_mcp.control.pitch import build_tenant_pitch
from cre_mcp.control.site_fit import (
    evaluate_tenant_site_fit,
    match_tenants_to_site,
)
from cre_mcp.control.spread import model_lease_creation_spread
from cre_mcp.control.structures import recommend_control_structure
from cre_mcp.control.vacant import detect_vacant
from cre_mcp.models.listings import Listing
from cre_mcp.tools.control_tools import find_control_opportunities


def test_drive_thru_high_traffic_site_fits_coffee_or_qsr() -> None:
    site = {
        "aadt": 48_000,
        "population_3mi": 75_000,
        "median_income": 82_000,
        "parcel_acres": 1.0,
        "building_sqft": 2_500,
        "has_drive_thru": True,
        "nearby_categories": ["grocery", "retail"],
    }
    matches = match_tenants_to_site(**site)
    leading_brands = {match["brand"] for match in matches[:5]}
    assert leading_brands & {
        "Starbucks",
        "Dutch Bros Coffee",
        "Dunkin'",
        "Panda Express",
        "Taco Bell",
    }
    starbucks = evaluate_tenant_site_fit("Starbucks", **site)
    assert starbucks["fit_score"] >= 0.8
    assert not starbucks["unmet"]


def test_vacant_second_generation_restaurant_is_a_candidate() -> None:
    listing = Listing(
        source="test",
        source_id="vacant-1",
        name="Former Restaurant",
        address="100 Main St",
        city="Phoenix",
        state="AZ",
        property_type="retail",
        property_subtype="freestanding restaurant",
        listing_type="for-lease",
        description="2nd generation restaurant, vacant and available now.",
        url="https://example.com/vacant-1",
    )
    result = detect_vacant(listing)
    assert result["is_vacant_candidate"] is True
    assert result["confidence"] > 0.5


def test_lease_creation_spread_math() -> None:
    result = model_lease_creation_spread(
        value_vacant=1_000_000,
        achievable_rent_psf=30,
        building_sqft=5_000,
        market_cap_rate=0.06,
        ti_psf=20,
        leasing_commission_pct=0.05,
        months_vacant=6,
        carry_annual=120_000,
        execution_risk_haircut=0.10,
    )
    assert result["value_leased"] == 2_500_000
    expected_costs = 100_000 + 7_500 + 60_000
    expected_gross_spread = 2_500_000 - 1_000_000 - expected_costs
    assert result["costs"] == expected_costs
    assert result["net_spread"] == expected_gross_spread * 0.90


def test_tenant_first_ranks_option_and_extended_close_high() -> None:
    recommendations = recommend_control_structure(needs_tenant_first=True)
    assert {item["name"] for item in recommendations[:2]} == {
        "purchase_option",
        "extended_close",
    }


def test_pitch_uses_passed_traffic_and_anchor() -> None:
    pitch = build_tenant_pitch(
        tenant_brand="Starbucks",
        address="100 Main St, Phoenix, AZ",
        aadt=42_000,
        nearby_anchors=["Chase"],
        population_3mi=68_000,
        achievable_rent_psf=42,
    )
    assert "~42,000 cars/day" in pitch["body"]
    assert "Chase" in pitch["body"]


async def test_control_screen_preserves_listing_raw_without_restricted_context() -> None:
    listing = Listing(
        source="test",
        source_id="raw-preservation-1",
        name="Raw preservation fixture",
        address="100 Main Street, Dallas, TX 75201",
        city="Dallas",
        state="TX",
        zip_code="75201",
        property_type="retail",
        url="https://example.test/raw-preservation-1",
        raw={"provider_marker": "must-survive-direct-call"},
    )

    with use_context(local_context()):
        result = await find_control_opportunities(
            [listing.model_dump(mode="json")]
        )

    assert result["opportunities"][0]["listing"]["raw"] == listing.raw
