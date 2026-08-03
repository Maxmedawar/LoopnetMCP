"""Contractual rent math: partial periods, steps, CPI, and percentage rent."""

import pytest

from cre_mcp.leases.models import CitedClaim, LeaseAbstract, RentPeriod
from cre_mcp.leases.schedule import rent_schedule


def _claim(value):
    return CitedClaim.stated(value, quote=str(value), locator="Synthetic", confidence=1.0)


def _period(start, end, monthly):
    return RentPeriod(start=_claim(start), end=_claim(end), monthly=_claim(monthly))


def test_partial_month_uses_actual_calendar_days():
    lease = LeaseAbstract(rent_schedule=[_period("2025-01-01", "2025-12-31", 3100.0)])

    rows = rent_schedule(lease, "2025-01-16", "2025-01-31")

    assert rows[0]["proration_factor"] == pytest.approx(16 / 31)
    assert rows[0]["base_rent"] == 1600.0
    assert rows[0]["total_cash_rent"] == 1600.0


def test_fixed_step_periods_change_monthly_cash_rent():
    lease = LeaseAbstract(rent_schedule=[
        _period("2025-01-01", "2025-01-31", 1000.0),
        _period("2025-02-01", "2025-12-31", 1200.0),
    ])

    rows = rent_schedule(lease, "2025-01-01", "2025-02-28")

    assert [row["base_rent"] for row in rows] == [1000.0, 1200.0]


def test_cpi_cap_binds_against_caller_supplied_indices():
    lease = LeaseAbstract(rent_schedule=[_period("2025-01-01", "2025-12-31", 1000.0)])
    lease.escalations.cpi_index = _claim("CPI-U")
    lease.escalations.cpi_cap_pct = _claim(0.05)
    lease.escalations.cpi_floor_pct = _claim(0.02)

    rows = rent_schedule(
        lease,
        "2025-01-01",
        "2025-01-31",
        cpi_values={"2024-01-01": 100.0, "2025-01-01": 110.0},
    )

    assert rows[0]["base_rent"] == 1050.0
    assert rows[0]["status"] == "calculated"


def test_percentage_rent_applies_only_above_monthly_share_of_breakpoint():
    lease = LeaseAbstract(rent_schedule=[_period("2025-01-01", "2025-12-31", 1000.0)])
    lease.escalations.percentage_rent = _claim(True)
    lease.escalations.percentage_rate = _claim(0.05)
    lease.escalations.percentage_breakpoint = _claim(1_200_000.0)
    lease.escalations.percentage_breakpoint_type = _claim("stated")

    rows = rent_schedule(lease, "2025-01-01", "2025-01-31", sales=150_000.0)

    assert rows[0]["percentage_rent"] == 2500.0
    assert rows[0]["total_cash_rent"] == 3500.0


def test_formula_input_omission_is_explicit_not_zero_filled():
    lease = LeaseAbstract(rent_schedule=[_period("2025-01-01", "2025-12-31", 1000.0)])
    lease.escalations.percentage_rent = _claim(True)
    lease.escalations.percentage_rate = _claim(0.05)
    lease.escalations.percentage_breakpoint = _claim(1_200_000.0)

    rows = rent_schedule(lease, "2025-01-01", "2025-01-31")

    assert rows[0]["percentage_rent"] is None
    assert rows[0]["total_cash_rent"] is None
    assert rows[0]["status"] == "missing_inputs"
    assert "sales" in rows[0]["missing_inputs"]
