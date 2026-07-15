from __future__ import annotations

import pytest

from cre_mcp.pmops.forensics import (
    EMERGENCY_RATIO_THRESHOLD_BPS,
    RISING_REPAIR_THRESHOLD_BPS,
    balance_validation,
    deferred_maintenance_screen,
)
from cre_mcp.pmops.preventive import pm_schedule


def test_pm_schedule_expands_multiple_tasks_and_cites_every_convention() -> None:
    result = pm_schedule(
        [
            {
                "asset": "Commerce Center",
                "system": "HVAC",
                "install_year": 2015,
                "last_service": "2024-01-31",
            },
            {"system": "roof", "last_service": None},
        ],
        as_of="2025-02-01",
    )

    hvac = [item for item in result["items"] if item["system"] == "hvac"]
    assert {item["convention"]["convention_id"] for item in hvac} == {
        "hvac_filter_quarterly",
        "hvac_annual_service",
    }
    assert all(item["due"] is True for item in hvac)
    assert all("Planning convention" in item["convention_citation"] for item in hvac)
    assert all(
        item["physical_rul_cross_link"]["read_only_source"]
        == "cre_mcp.physical.rul.LIFESPAN_CONVENTIONS"
        for item in hvac
    )
    assert hvac[0]["physical_rul_cross_link"]["age_years"] == 10

    roof = [item for item in result["items"] if item["system"] == "roof"]
    assert len(roof) == 1
    assert roof[0]["due"] is None
    assert roof[0]["next_due"] is None
    assert "not supplied" in roof[0]["date_basis"]
    assert result["counts"] == {"due": 2, "upcoming": 0, "unknown": 1, "total": 3}


def test_pm_schedule_rejects_silent_shape_drift() -> None:
    with pytest.raises(ValueError, match="unrecognized inputs.*last_serviced"):
        pm_schedule([{"system": "hvac", "last_serviced": "2025-01-01"}])
    with pytest.raises(ValueError, match="unknown system"):
        pm_schedule([{"system": "teleporter"}], as_of="2025-01-01")


def test_deferred_maintenance_screen_shows_basis_and_exact_arithmetic() -> None:
    result = deferred_maintenance_screen(
        [
            {"period": "2025-01", "category": "Repairs", "amount_cents": 10_000},
            {"period": "2025-02", "category": "Repairs", "amount_cents": 10_000},
            {"period": "2025-03", "category": "Repairs", "amount_cents": 20_000},
            {
                "period": "2025-04",
                "category": "Emergency repairs",
                "amount_cents": 30_000,
                "memo": "after-hours response",
            },
        ]
    )

    by_id = {item["heuristic_id"]: item for item in result["heuristics"]}
    trend = by_id["rising_repairs_without_capex"]
    assert trend["triggered"] is True
    assert trend["thresholds"]["minimum_recent_average_increase_bps"] == RISING_REPAIR_THRESHOLD_BPS
    assert trend["arithmetic"]["early_repair_sum_cents"] == 20_000
    assert trend["arithmetic"]["recent_repair_sum_cents"] == 50_000
    assert trend["arithmetic"]["recorded_capex_cents"] == 0
    assert "split chronologically" in trend["basis"]

    emergency = by_id["high_emergency_repair_ratio"]
    assert emergency["triggered"] is True
    assert emergency["thresholds"]["minimum_emergency_share_bps"] == EMERGENCY_RATIO_THRESHOLD_BPS
    assert emergency["arithmetic"]["emergency_repair_cents"] == 30_000
    assert emergency["arithmetic"]["total_repair_cents"] == 70_000
    assert result["screening_flag"] is True
    assert result["deferred_maintenance_proven"] is False
    assert "not a causal finding" in result["honesty"]


def test_deferred_screen_rejects_unknown_fields_and_non_integer_money() -> None:
    with pytest.raises(ValueError, match="unrecognized inputs.*ammount_cents"):
        deferred_maintenance_screen(
            [
                {
                    "period": "2025-01",
                    "category": "Repairs",
                    "amount_cents": 100,
                    "ammount_cents": 100,
                }
            ]
        )
    with pytest.raises(ValueError, match="integer number of cents"):
        deferred_maintenance_screen(
            [{"period": "2025-01", "category": "Repairs", "amount_cents": 1.25}]
        )


def test_balance_validation_is_penny_exact_and_surfaces_one_cent_delta() -> None:
    expected = {
        "deposits_held_cents": 500_00,
        "prepaid_cents": 125_00,
        "ar_cents": 900_01,
        "ap_cents": 300_00,
    }
    exact = balance_validation(dict(expected), expected)
    assert exact["penny_exact"] is True
    assert exact["balanced"] is True
    assert all(line["delta_cents"] == 0 for line in exact["lines"])

    actual = dict(expected)
    actual["ar_cents"] += 1
    mismatch = balance_validation(actual, expected)
    assert mismatch["penny_exact"] is False
    assert mismatch["mismatches"] == ["ar_cents"]
    assert mismatch["by_line"]["ar_cents"]["delta_cents"] == 1
    assert mismatch["by_line"]["ar_cents"]["arithmetic"] == "90002 - 90001 = 1 cents"


def test_balance_validation_requires_exact_four_line_shape() -> None:
    balances = {
        "deposits_held_cents": 0,
        "prepaid_cents": 0,
        "ar_cents": 0,
        "ap_cents": 0,
        "cash_cents": 1,
    }
    with pytest.raises(ValueError, match="unrecognized inputs.*cash_cents"):
        balance_validation(balances, {key: 0 for key in balances if key != "cash_cents"})


def test_balance_validation_books_source_derives_only_provable_ar() -> None:
    class ReadOnlyBooks:
        def list_charges(self):
            return [
                {"charge_id": "c1", "tenancy_id": "t1", "amount_cents": 10_001},
                {"charge_id": "c2", "tenancy_id": "t1", "amount_cents": 5_000},
            ]

        def list_receipts(self):
            return [
                {
                    "receipt_id": "r1",
                    "tenancy_id": "t1",
                    "amount_cents": 10_001,
                    "matched_charge_ids": ["c1"],
                    "status": "matched",
                },
                {
                    "receipt_id": "r2",
                    "tenancy_id": None,
                    "amount_cents": 2_000,
                    "matched_charge_ids": [],
                    "status": "unmatched",
                },
            ]

        def list_tenancies(self):
            return [{"tenancy_id": "t1"}]

    result = balance_validation(
        {
            "deposits_held_cents": 0,
            "prepaid_cents": 0,
            "ar_cents": 5_000,
            "ap_cents": 0,
        },
        store=ReadOnlyBooks(),  # type: ignore[arg-type]
    )

    assert result["by_line"]["ar_cents"]["match"] is True
    assert result["by_line"]["ar_cents"]["delta_cents"] == 0
    assert result["unavailable_lines"] == [
        "deposits_held_cents",
        "prepaid_cents",
        "ap_cents",
    ]
    assert result["penny_exact"] is False
    assert result["all_available_lines_match"] is True
    assert result["source_basis"]["valid_matched_cash_cents"] == 10_001
    assert "not assumed" in result["source_basis"]["unavailable_reason"]["prepaid_cents"]
