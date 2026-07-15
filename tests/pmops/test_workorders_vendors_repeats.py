from __future__ import annotations

import pytest

from cre_mcp.pmops.repeats import repeat_repair_analysis
from cre_mcp.pmops.vendors import compare_vendors, record_vendor
from cre_mcp.pmops.workorders import record_workorder, triage_queue


def _order(
    db_path,
    *,
    workorder_id: str,
    system: str = "hvac",
    opened: str = "2026-06-01",
    severity: str = "routine",
    status: str = "open",
    due: str | None = None,
    cost_cents: int | None = None,
    vendor: str | None = None,
):
    return record_workorder(
        "asset-1",
        system,
        f"repair {workorder_id}",
        opened,
        severity,
        status,
        "101",
        due,
        cost_cents,
        vendor,
        workorder_id,
        db_path=db_path,
    )


def test_life_safety_gate_is_unconditional_then_sla_and_repeat(tmp_path):
    db = tmp_path / "pm.db"
    _order(
        db,
        workorder_id="life",
        system="fire alarm",
        opened="2026-07-10",
        severity="life_safety",
        due="2026-08-01",
        cost_cents=1,
    )
    _order(
        db,
        workorder_id="expensive-overdue",
        system="roof",
        opened="2026-05-01",
        due="2026-06-01",
        cost_cents=999_999_999,
    )
    for index, opened in enumerate(("2026-03-01", "2026-04-01", "2026-05-01"), 1):
        _order(
            db,
            workorder_id=f"repeat-{index}",
            opened=opened,
            due="2026-08-01",
            cost_cents=100,
        )

    result = triage_queue("2026-07-14", db_path=db)
    rows = result["queue"]

    assert rows[0]["workorder_id"] == "life"
    assert rows[0]["is_life_safety_gate"] is True
    assert rows[1]["workorder_id"] == "expensive-overdue"
    assert rows[1]["sla_overdue"] is True
    assert all(row["repeat_offender_system"] for row in rows[2:])
    assert result["conventions"]["ranking_order"][0] == "life_safety_first_unconditional"
    assert result["conventions"]["repeat_threshold_orders"] == 3
    assert result["conventions"]["weights"]["cost_points_cap"] == 25


def test_workorder_record_is_durable_strict_and_nullable(tmp_path):
    db = tmp_path / "pm.db"
    row = _order(db, workorder_id="wo-1")
    assert row["workorder_id"] == "wo-1"
    assert row["due"] is None
    assert row["cost_cents"] is None
    assert row["vendor"] is None
    assert row["source_ref"]["table"] == "pm_workorders"

    assert triage_queue("2026-07-14", db_path=db)["queue"][0]["workorder_id"] == "wo-1"
    with pytest.raises(ValueError, match="integer number of cents"):
        _order(db, workorder_id="lossy", cost_cents=1.25)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        record_workorder(  # type: ignore[call-arg]
            "asset-1",
            "hvac",
            "repair",
            "2026-01-01",
            "routine",
            "open",
            unrecognized="must not be dropped",
            db_path=db,
        )


def test_vendor_comparison_is_honest_empty_without_workorder_history(tmp_path):
    db = tmp_path / "pm.db"
    record_vendor("No History HVAC", "HVAC", db_path=db)

    result = compare_vendors("hvac", "2026-07-14", db_path=db)

    assert result["status"] == "no_recorded_workorder_history"
    assert result["vendors"] == []
    assert result["comparisons"] == []
    assert result["registered_vendors_without_order_history"] == ["No History HVAC"]
    assert "unavailable" in result["honest_gaps"][0].lower()


def test_vendor_comparison_uses_recorded_cost_sla_and_repeat_only(tmp_path):
    db = tmp_path / "pm.db"
    record_vendor("Alpha Mechanical", "HVAC", "2027-01-01", "$125 dispatch", db_path=db)
    record_vendor("Unobserved Mechanical", "HVAC", db_path=db)
    _order(
        db,
        workorder_id="alpha-1",
        opened="2026-01-01",
        due="2026-01-05",
        status="closed",
        cost_cents=100,
        vendor="Alpha Mechanical",
    )
    _order(
        db,
        workorder_id="alpha-2",
        opened="2026-02-01",
        due="2026-02-05",
        status="open",
        cost_cents=101,
        vendor="Alpha Mechanical",
    )

    result = compare_vendors("HVAC", "2026-07-14", db_path=db)
    alpha = result["vendors"][0]

    assert result["status"] == "recorded_history"
    assert alpha["recorded_order_count"] == 2
    assert alpha["order_count"] == 2
    assert alpha["cost"]["total_recorded_cost_cents"] == 201
    assert alpha["cost"]["average_recorded_cost_cents"] == 101
    assert alpha["average_recorded_cost_cents"] == 101
    assert alpha["response"]["actual_response_days"] is None
    assert alpha["response"]["status"] == "unavailable"
    assert alpha["recorded_sla_exposure"]["due_dated_active_order_count"] == 1
    assert alpha["recorded_sla_exposure"]["open_overdue_count"] == 1
    assert alpha["repeat_observation"]["repeat_order_count"] == 1
    assert alpha["repeat_observation"]["repeat_rate"] == 0.5
    assert alpha["repeat_rate"] == 0.5
    assert result["registered_vendors_without_order_history"] == ["Unobserved Mechanical"]


def test_repeat_cluster_has_cents_arithmetic_and_physical_replacement_range(tmp_path):
    db = tmp_path / "pm.db"
    for index, (opened, cost) in enumerate(
        (("2025-01-15", 100_000), ("2025-09-15", 200_000), ("2026-06-15", 300_000)),
        1,
    ):
        _order(
            db,
            workorder_id=f"hvac-{index}",
            opened=opened,
            cost_cents=cost,
        )

    result = repeat_repair_analysis(
        "hvac",
        24,
        "2026-07-14",
        1_000,
        db_path=db,
    )
    cluster = result["clusters"][0]

    assert cluster["order_count"] == 3
    assert cluster["repeat_order_count"] == 2
    assert cluster["recorded_repair_cost"]["cumulative_known_cost_cents"] == 600_000
    assert cluster["cumulative_cost_cents"] == 600_000
    assert cluster["recorded_repair_cost"]["coverage_complete"] is True
    assert cluster["replacement_cost_convention"]["rate_range_cents"] == {
        "low": 1_200,
        "high": 3_000,
        "unit": "USD/building_sf",
    }
    assert cluster["replacement_cost_convention"]["replacement_cost_range_cents"] == {
        "low": 1_200_000,
        "high": 3_000_000,
    }
    assert cluster["replacement_cost_range_cents"] == {
        "low": 1_200_000,
        "high": 3_000_000,
    }
    assert cluster["repair_vs_replace"]["repair_cost_as_percent_of_replacement_low"] == 50.0
    assert cluster["repair_vs_replace"]["arithmetic"]["known_repair_cost_cents"] == 600_000
    assert cluster["repair_vs_replace"]["root_cause_review_required"] is True


def test_repeat_analysis_never_invents_replacement_total_without_quantity(tmp_path):
    db = tmp_path / "pm.db"
    _order(db, workorder_id="roof-1", system="roof", opened="2026-01-01", cost_cents=10_000)
    _order(db, workorder_id="roof-2", system="roof", opened="2026-02-01", cost_cents=20_000)

    result = repeat_repair_analysis("roof", as_of="2026-07-14", db_path=db)
    cluster = result["clusters"][0]

    assert cluster["replacement_cost_convention"]["status"] == "unit_convention_only"
    assert cluster["replacement_cost_convention"]["rate_range_cents"]["low"] == 800
    assert cluster["replacement_cost_convention"]["replacement_cost_range_cents"] is None
    assert cluster["repair_vs_replace"]["status"] == "not_comparable_without_replacement_total"


def test_repeat_window_and_integer_month_validation(tmp_path):
    db = tmp_path / "pm.db"
    _order(db, workorder_id="old", opened="2024-01-01", cost_cents=100)
    _order(db, workorder_id="recent", opened="2026-01-01", cost_cents=100)

    result = repeat_repair_analysis("hvac", 12, "2026-07-14", db_path=db)
    assert result["orders_in_window"] == 1
    assert result["clusters"] == []
    with pytest.raises(ValueError, match="positive integer"):
        repeat_repair_analysis(window_months=True, db_path=db)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        repeat_repair_analysis(
            "hvac",
            as_of="2026-07-14",
            building_sf=-1,
            db_path=db,
        )
