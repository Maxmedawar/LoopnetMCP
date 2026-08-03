from __future__ import annotations

from cre_mcp.mlops.breach_watch import breach_report, record_watch_item
from cre_mcp.mlops.exit_package import package_control_exit


def test_breach_watch_orders_date_then_severity_and_keeps_resolved_separate(tmp_path):
    db_path = tmp_path / "watch.db"
    rows = (
        ("payment_late", "2026-07-13", "low", "open", "past"),
        ("maintenance", "2026-07-15", "medium", "monitoring", "medium"),
        ("insurance_lapse", "2026-07-15", "critical", "open", "critical"),
        ("coi_expiry", "2026-07-14", "high", "cured", "resolved"),
    )
    for item, when, severity, status, watch_id in rows:
        record_watch_item(
            "ml-219",
            item,
            when,
            severity,
            status,
            db_path=db_path,
            watch_id=watch_id,
        )

    report = breach_report("ml-219", as_of="2026-07-14", db_path=db_path)

    assert next(iter(report)) == "rent_owed_vs_received_exposure"
    assert [row["watch_id"] for row in report["items"]] == [
        "past",
        "critical",
        "medium",
    ]
    assert [row["days_to_consequence"] for row in report["items"]] == [-1, 1, 1]
    assert [row["watch_id"] for row in report["resolved_items"]] == ["resolved"]
    assert report["owner_side_default_exposure"]["highest_active_severity"] == "critical"


def test_exit_capitalizes_only_hand_computed_net_spread_and_flags_consent_gap():
    result = package_control_exit(
        {
            "position_id": "ml-220",
            "master_rent_owed_cents": 500_000,
            "sublease_received_cents": 800_000,
            "expense_cents": 100_000,
            "remaining_term_months": 120,
            "cap_rate_range": ["0.10", "0.15"],
        },
        buyer_view=True,
    )

    summary = result["assignable_value_summary"]
    assert next(iter(result)) == "rent_owed_vs_received_exposure"
    assert summary["net_annual_spread_cents"] == 2_400_000
    assert summary["spread_capitalization_value_range_cents"] == {
        "low": 16_000_000,
        "high": 24_000_000,
    }
    assert summary["undiscounted_remaining_net_spread_cents"] == 24_000_000
    assert summary["term_limited_value_indication_range_cents"] == {
        "low": 16_000_000,
        "high": 24_000_000,
    }
    assert result["consent_cross_link"]["checklist_job"] == 214
    assert any(
        "consent screen did not run" in gap
        for gap in result["honesty"]["assumptions_and_gaps"]
    )


def test_negative_exit_spread_does_not_invent_positive_assignable_value():
    result = package_control_exit(
        {
            "net_annual_spread_cents": -1,
            "remaining_term_months": 12,
        },
        buyer_view=False,
    )

    value = result["assignable_value_summary"]
    assert value["spread_capitalization_value_range_cents"] == {
        "low": None,
        "high": None,
    }
    assert any(
        risk["risk"] == "non_positive_net_spread" for risk in result["honest_risks"]
    )
