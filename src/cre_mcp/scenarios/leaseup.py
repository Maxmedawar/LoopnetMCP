"""Deterministic monthly lease-up cash model."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from cre_mcp.scenarios._common import HONESTY_LABEL, add_issue, as_number


def _monthly_carry(carry_costs: Any) -> float | None:
    if isinstance(carry_costs, Mapping):
        for key in ("monthly", "monthly_carry", "monthly_carry_cost"):
            if key in carry_costs:
                return as_number(carry_costs.get(key))
        return None
    return as_number(carry_costs)


def _velocity(leasing_velocity: Any) -> tuple[str | None, float | None]:
    if isinstance(leasing_velocity, Mapping):
        suites = as_number(leasing_velocity.get("suites_per_month"))
        if suites is not None:
            return "suites_per_month", suites
        sf = as_number(leasing_velocity.get("sf_per_month"))
        if sf is not None:
            return "sf_per_month", sf
        return None, None
    return "suites_per_month", as_number(leasing_velocity)


def _suite_monthly_rent(suite: Mapping[str, Any], sf: float | None) -> float | None:
    monthly = as_number(suite.get("monthly_rent"))
    if monthly is not None:
        return monthly
    annual = as_number(suite.get("annual_rent"))
    if annual is not None:
        return annual / 12
    rent_per_sf = None
    for key in ("annual_rent_per_sf", "rent_per_sf"):
        rent_per_sf = as_number(suite.get(key))
        if rent_per_sf is not None:
            break
    if rent_per_sf is not None and sf is not None:
        return rent_per_sf * sf / 12
    monthly_per_unit = as_number(suite.get("monthly_rent_per_unit"))
    units = as_number(suite.get("units"))
    if monthly_per_unit is not None and units is not None:
        return monthly_per_unit * units
    return None


def model_lease_up(
    suites: Sequence[Mapping[str, Any]] | None,
    leasing_velocity: float | Mapping[str, Any] | None,
    downtime_months: float | None,
    ti_per_sf: float | None,
    lc_per_sf: float | None,
    free_rent_months: float | None,
    carry_costs: float | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Model monthly lease starts, concessions, leasing costs, and cash NOI.

    Schedule entries require ``available_month`` plus rent expressed as monthly,
    annual, annual/SF, or monthly/unit. Numeric velocity means suites/month; a
    mapping may instead supply ``sf_per_month``. Suites are leased in availability
    order. Stabilization is the first month when every scheduled suite is both
    commenced and out of free rent. This deterministic ordering is a CONVENTION,
    not a forecast of leasing outcomes.
    """
    issues: list[str] = []
    schedule = list(suites) if suites is not None else []
    if not schedule:
        add_issue(issues, "cannot compute lease-up because suites schedule is missing or empty")
    velocity_basis, velocity = _velocity(leasing_velocity)
    if velocity is None or velocity <= 0:
        add_issue(
            issues, "cannot compute lease-up because leasing_velocity must be positive"
        )
    downtime = as_number(downtime_months)
    ti = as_number(ti_per_sf)
    lc = as_number(lc_per_sf)
    free_rent = as_number(free_rent_months)
    carry = _monthly_carry(carry_costs)
    for name, value in (
        ("downtime_months", downtime),
        ("ti_per_sf", ti),
        ("lc_per_sf", lc),
        ("free_rent_months", free_rent),
        ("monthly carry_costs", carry),
    ):
        if value is None:
            add_issue(issues, f"cannot compute lease-up because {name} is missing")
        elif value < 0:
            add_issue(issues, f"cannot compute lease-up because {name} is negative")

    normalized: list[dict[str, Any]] = []
    for index, raw_suite in enumerate(schedule):
        if not isinstance(raw_suite, Mapping):
            add_issue(issues, f"cannot compute lease-up because suite {index} is not a mapping")
            continue
        suite = dict(raw_suite)
        name = str(suite.get("name", suite.get("id", f"suite_{index + 1}")))
        sf = None
        for key in ("sf", "rentable_sf", "square_feet"):
            sf = as_number(suite.get(key))
            if sf is not None:
                break
        if sf is None:
            units = as_number(suite.get("units"))
            sf_per_unit = as_number(suite.get("sf_per_unit"))
            if units is not None and sf_per_unit is not None:
                sf = units * sf_per_unit
        available = as_number(suite.get("available_month"))
        monthly_rent = _suite_monthly_rent(suite, sf)
        suite_ti = as_number(suite.get("ti_per_sf")) if "ti_per_sf" in suite else ti
        suite_lc = as_number(suite.get("lc_per_sf")) if "lc_per_sf" in suite else lc
        suite_free = (
            as_number(suite.get("free_rent_months"))
            if "free_rent_months" in suite
            else free_rent
        )
        if available is None:
            add_issue(
                issues,
                f"cannot compute lease-up because {name}.available_month is missing",
            )
        elif available < 0:
            add_issue(
                issues,
                f"cannot compute lease-up because {name}.available_month is negative",
            )
        if monthly_rent is None or monthly_rent < 0:
            add_issue(
                issues,
                f"cannot compute lease-up because {name} rent is missing or invalid",
            )
        for field, value in (
            ("ti_per_sf", suite_ti),
            ("lc_per_sf", suite_lc),
            ("free_rent_months", suite_free),
        ):
            if value is None:
                add_issue(
                    issues,
                    f"cannot compute lease-up because {name}.{field} is missing",
                )
            elif value < 0:
                add_issue(
                    issues,
                    f"cannot compute lease-up because {name}.{field} is negative",
                )
        if (suite_ti not in (None, 0) or suite_lc not in (None, 0)) and (
            sf is None or sf <= 0
        ):
            add_issue(
                issues,
                f"cannot compute lease-up because {name}.sf is required for TI/LC",
            )
        if velocity_basis == "sf_per_month" and (sf is None or sf <= 0):
            add_issue(
                issues,
                f"cannot compute lease-up because {name}.sf is required for sf_per_month velocity",
            )
        normalized.append(
            {
                "name": name,
                "sf": sf,
                "available_month": available,
                "monthly_rent": monthly_rent,
                "ti_per_sf": suite_ti,
                "lc_per_sf": suite_lc,
                "free_rent_months": suite_free,
                "supplied": suite,
            }
        )

    assumptions = {
        "supplied_suites": [dict(suite) for suite in schedule if isinstance(suite, Mapping)],
        "leasing_velocity": leasing_velocity,
        "velocity_basis": velocity_basis,
        "downtime_months": downtime_months,
        "ti_per_sf": ti_per_sf,
        "lc_per_sf": lc_per_sf,
        "free_rent_months": free_rent_months,
        "carry_costs": carry_costs,
        "model_conventions": [
            "Suites lease in available-month order; no probabilistic absorption is inferred.",
            "Rent/SF is annual unless explicitly named monthly.",
            "TI and LC are paid in full at lease commencement.",
            "Fractional availability, downtime, and free-rent periods round up to whole months.",
            "Carry is charged from month 0 through the stabilization month.",
            "Operating expenses beyond stated carry costs are not modeled.",
        ],
    }
    if issues:
        return {
            "honesty_label": HONESTY_LABEL,
            "monthly_cash_noi_curve": [],
            "stabilization_month": None,
            "full_occupancy_month": None,
            "total_carry": None,
            "total_lease_up_cost": None,
            "total_carry_plus_lease_up_cost": None,
            "peak_negative_cash": None,
            "assumptions": assumptions,
            "not_computable": issues,
        }

    assert velocity is not None
    assert downtime is not None
    assert ti is not None
    assert lc is not None
    assert free_rent is not None
    assert carry is not None
    normalized.sort(key=lambda suite: (suite["available_month"], suite["name"]))
    first_ready = min(int(math.ceil(suite["available_month"] + downtime)) for suite in normalized)
    work_before = 0.0
    for index, suite in enumerate(normalized):
        ready = int(math.ceil(suite["available_month"] + downtime))
        if velocity_basis == "sf_per_month":
            slot_offset = math.floor(work_before / velocity)
            work_before += float(suite["sf"])
        else:
            slot_offset = math.floor(index / velocity)
        suite["lease_start_month"] = max(ready, first_ready + slot_offset)
        suite["free_rent_months"] = int(math.ceil(suite["free_rent_months"]))
        suite["ti_cost"] = float(suite["sf"] or 0) * float(suite["ti_per_sf"])
        suite["lc_cost"] = float(suite["sf"] or 0) * float(suite["lc_per_sf"])
        suite["free_rent_cost"] = (
            float(suite["monthly_rent"]) * suite["free_rent_months"]
        )

    full_occupancy_month = max(suite["lease_start_month"] for suite in normalized)
    stabilization_month = max(
        suite["lease_start_month"] + suite["free_rent_months"]
        for suite in normalized
    )
    curve: list[dict[str, Any]] = []
    cumulative = 0.0
    for month in range(0, stabilization_month + 1):
        contractual = sum(
            float(suite["monthly_rent"])
            for suite in normalized
            if month >= suite["lease_start_month"]
        )
        collected = sum(
            float(suite["monthly_rent"])
            for suite in normalized
            if month
            >= suite["lease_start_month"] + suite["free_rent_months"]
        )
        ti_paid = sum(
            suite["ti_cost"]
            for suite in normalized
            if month == suite["lease_start_month"]
        )
        lc_paid = sum(
            suite["lc_cost"]
            for suite in normalized
            if month == suite["lease_start_month"]
        )
        cash_noi = collected - carry - ti_paid - lc_paid
        cumulative += cash_noi
        curve.append(
            {
                "month": month,
                "gross_contractual_rent": contractual,
                "collected_rent": collected,
                "free_rent_concession": contractual - collected,
                "ti_paid": ti_paid,
                "lc_paid": lc_paid,
                "carry_cost": carry,
                "cash_noi": cash_noi,
                "cumulative_cash": cumulative,
            }
        )

    total_ti = sum(suite["ti_cost"] for suite in normalized)
    total_lc = sum(suite["lc_cost"] for suite in normalized)
    total_free_rent = sum(suite["free_rent_cost"] for suite in normalized)
    total_carry = carry * len(curve)
    total_lease_up = total_ti + total_lc + total_free_rent
    peak_negative_cash = max(0.0, -min(point["cumulative_cash"] for point in curve))
    assumptions["normalized_schedule"] = normalized
    return {
        "honesty_label": (
            "CONVENTION: deterministic lease-up schedule, not an absorption forecast"
        ),
        "monthly_cash_noi_curve": curve,
        "stabilization_month": stabilization_month,
        "full_occupancy_month": full_occupancy_month,
        "total_carry": total_carry,
        "total_ti": total_ti,
        "total_lc": total_lc,
        "total_free_rent_concession": total_free_rent,
        "total_lease_up_cost": total_lease_up,
        "total_carry_plus_lease_up_cost": total_carry + total_lease_up,
        "peak_negative_cash": peak_negative_cash,
        "peak_negative_monthly_cash_noi": min(point["cash_noi"] for point in curve),
        "assumptions": assumptions,
        "not_computable": [],
    }
