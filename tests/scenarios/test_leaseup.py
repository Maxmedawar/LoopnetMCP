"""Hand-computed monthly lease-up tests."""

import pytest

from cre_mcp.scenarios.leaseup import model_lease_up


def _suites():
    return [
        {
            "name": "A",
            "sf": 1_000,
            "available_month": 0,
            "annual_rent_per_sf": 12,
        },
        {
            "name": "B",
            "sf": 1_000,
            "available_month": 0,
            "annual_rent_per_sf": 12,
        },
    ]


def test_monthly_curve_and_cost_totals_match_hand_math():
    result = model_lease_up(_suites(), 1, 1, 10, 2, 1, 500)

    assert result["full_occupancy_month"] == 2
    assert result["stabilization_month"] == 3
    assert [month["cash_noi"] for month in result["monthly_cash_noi_curve"]] == [
        -500,
        -12_500,
        -11_500,
        1_500,
    ]
    assert result["total_carry"] == 2_000
    assert result["total_ti"] == 20_000
    assert result["total_lc"] == 4_000
    assert result["total_free_rent_concession"] == 2_000
    assert result["total_lease_up_cost"] == 26_000
    assert result["total_carry_plus_lease_up_cost"] == 28_000
    assert result["peak_negative_cash"] == 24_500
    assert result["peak_negative_monthly_cash_noi"] == -12_500


def test_faster_velocity_stabilizes_no_later():
    slow = model_lease_up(_suites(), 1, 1, 0, 0, 0, 0)
    fast = model_lease_up(_suites(), 2, 1, 0, 0, 0, 0)

    assert fast["stabilization_month"] < slow["stabilization_month"]


def test_sf_velocity_and_unit_rent_schedule_are_supported():
    suites = [
        {
            "name": "Units",
            "units": 2,
            "sf_per_unit": 500,
            "available_month": 0,
            "monthly_rent_per_unit": 800,
        }
    ]
    result = model_lease_up(
        suites,
        {"sf_per_month": 1_000},
        0,
        0,
        0,
        0,
        100,
    )

    assert result["stabilization_month"] == 0
    assert result["monthly_cash_noi_curve"][0]["collected_rent"] == 1_600
    assert result["monthly_cash_noi_curve"][0]["cash_noi"] == 1_500


def test_missing_available_month_is_explicit_and_returns_no_curve():
    suites = _suites()
    del suites[0]["available_month"]
    result = model_lease_up(suites, 1, 1, 10, 2, 1, 500)

    assert result["monthly_cash_noi_curve"] == []
    assert result["stabilization_month"] is None
    assert any("A.available_month is missing" in message for message in result["not_computable"])


def test_missing_sf_is_explicit_for_sf_velocity():
    suites = [{"name": "A", "available_month": 0, "annual_rent": 12_000}]
    result = model_lease_up(
        suites, {"sf_per_month": 1_000}, 0, 0, 0, 0, 0
    )

    assert result["monthly_cash_noi_curve"] == []
    assert any("sf is required for sf_per_month" in message for message in result["not_computable"])


@pytest.mark.parametrize(
    "argument_index,bad_value,expected",
    [
        (1, 0, "leasing_velocity must be positive"),
        (2, -1, "downtime_months is negative"),
        (3, None, "ti_per_sf is missing"),
        (6, None, "monthly carry_costs is missing"),
    ],
)
def test_degenerate_global_inputs_are_not_defaulted(argument_index, bad_value, expected):
    arguments = [_suites(), 1, 1, 10, 2, 1, 500]
    arguments[argument_index] = bad_value
    result = model_lease_up(*arguments)

    assert result["monthly_cash_noi_curve"] == []
    assert any(expected in message for message in result["not_computable"])
