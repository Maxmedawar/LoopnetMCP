from __future__ import annotations

import pytest

from cre_mcp.leasing.capacity import CONVENTION_NOTE, tenant_sales_capacity


def test_grocery_capacity_math_is_hand_computable_and_labeled() -> None:
    result = tenant_sales_capacity(
        "grocery",
        {"population": 85_000, "median_income": 72_000, "traffic_aadt": 31_000},
        {"sf": 40_000},
    )

    assert result["sales_psf_range"]["low"] == 450.0
    assert result["sales_psf_range"]["high"] == 750.0
    assert result["annual_sales_range"]["low"] == 18_000_000.0
    assert result["annual_sales_range"]["high"] == 30_000_000.0
    assert result["occupancy_cost_ratio_band"]["low"] == 0.02
    assert result["occupancy_cost_ratio_band"]["high"] == 0.04
    assert result["sustainable_annual_rent_range"]["low"] == 360_000.0
    assert result["sustainable_annual_rent_range"]["high"] == 1_200_000.0
    assert result["sustainable_rent_psf_range"]["low"] == 9.0
    assert result["sustainable_rent_psf_range"]["high"] == 30.0
    assert result["source_note"] == CONVENTION_NOTE
    assert result["trade_area_context"]["used_in_arithmetic"] is False
    assert "does not assert" in result["decision_caveat"]


def test_natural_breakpoint_and_alias_are_transparent() -> None:
    result = tenant_sales_capacity("dollar_store", {}, {"sf": 10_000})

    assert result["category"] == "dollar"
    assert result["natural_percentage_rent_breakpoint_range"]["formula"] == (
        "annual base rent / percentage-rent rate"
    )
    assert result["natural_percentage_rent_breakpoint_range"]["low"] == pytest.approx(
        1_440_000.0
    )
    assert result["natural_percentage_rent_breakpoint_range"]["high"] == pytest.approx(
        7_000_000.0
    )


@pytest.mark.parametrize("sf", [None, 0, -1, True])
def test_capacity_rejects_missing_or_invalid_sf(sf: object) -> None:
    with pytest.raises(ValueError):
        tenant_sales_capacity("coffee", {}, {"sf": sf})
