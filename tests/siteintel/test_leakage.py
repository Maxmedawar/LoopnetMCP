from __future__ import annotations

from cre_mcp.siteintel.leakage import (
    BLS_CEX_CATEGORY_SHARES,
    BLS_CEX_SOURCE,
    HONESTY_LABEL,
    retail_gap_note,
)


def test_retail_gap_direction_math_for_leakage_and_surplus() -> None:
    base = {
        "population": 1_000,
        "median_household_income": 50_000,
        "osm_anchor_counts": {"restaurants": 2},
        "annual_capacity_per_anchor": 1_000_000,
    }
    leakage = retail_gap_note(base, "restaurant")
    surplus = retail_gap_note(
        {**base, "osm_anchor_counts": {"food_away_from_home": 4}},
        "food away from home",
    )

    expected_potential = round(
        1_000 * 50_000 * BLS_CEX_CATEGORY_SHARES["food_away_from_home"], 2
    )
    assert leakage["direction"] == "leakage"
    assert surplus["direction"] == "surplus"
    assert (
        leakage["demand_convention"]["spending_potential_proxy"]
        == expected_potential
    )
    assert leakage["honesty_label"] == HONESTY_LABEL
    assert HONESTY_LABEL in leakage["notes"]


def test_retail_gap_accepts_trade_area_profile_demographic_hooks() -> None:
    profile = {
        "demographic_inputs": {
            "population": 10_000,
            "median_household_income": 75_000,
        },
        "osm_anchors": {"anchor_count": 1},
    }
    result = retail_gap_note(profile, "apparel")

    assert result["category"] == "apparel_and_services"
    assert result["existing_supply_proxy"]["measure"] == "OpenStreetMap anchor count"
    assert result["source"]["publisher"] == "U.S. Bureau of Labor Statistics"


def test_bls_convention_table_is_exposed_with_citation_metadata() -> None:
    assert BLS_CEX_CATEGORY_SHARES["entertainment"] == 0.046
    assert BLS_CEX_SOURCE["dataset"] == "Consumer Expenditure Surveys, 2024"
    assert BLS_CEX_SOURCE["source_url"].startswith("https://www.bls.gov/")
    assert "convention" in BLS_CEX_SOURCE["convention_note"].casefold()


def test_retail_gap_validation_stays_at_error_boundary() -> None:
    assert "error" in retail_gap_note({}, "restaurant")
    assert "error" in retail_gap_note(
        {
            "population": 1_000,
            "median_household_income": 50_000,
            "osm_anchor_count": 1,
        },
        "not-a-bls-category",
    )
