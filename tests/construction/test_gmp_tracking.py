"""GMP reconciliation and durable critical-item tracking tests."""

from __future__ import annotations

import sqlite3

from cre_mcp.construction.draws import forecast_draws
from cre_mcp.construction.gmp import reconcile_gmp
from cre_mcp.construction.tracking import critical_path_slippage, record_item, track_items


def test_gmp_exposes_unpriced_allowance_and_contingency_risk():
    result = reconcile_gmp(
        {
            "line_items": [{"scope": "Foundations", "amount_cents": 1_000_000}],
            "allowances": [{"scope": "Fire alarm", "amount_cents": 100_000}],
            "contingency": 40_000,
            "clarifications": ["Elevator scope excluded by owner"],
        },
        ["Foundations", "Fire alarm", "Elevators"],
    )

    assert "error" not in result
    assert result["allowance_exposure_total_cents"] == 100_000
    assert set(result["unpriced_scope_items"]) == {"Fire alarm", "Elevators"}
    assert result["contingency_adequacy"] == "below_convention"
    assert result["clarification_risk_flags"][0]["severity"] == "high"
    assert result["review_flags"]["gc_review_required"] is True
    assert "convention until bid" in result["honesty"].casefold()


def test_tracking_persists_owned_table_and_reports_only_open_critical_slippage(tmp_path):
    db_path = tmp_path / "construction.db"
    record_item(
        "P-1", "rfi", "RFI-001", "2026-01-01", "2026-01-10", "open", True, db_path
    )
    record_item(
        "P-1", "rfi", "RFI-002", "2026-01-01", "2026-01-10", "answered", True, db_path
    )
    record_item(
        "P-1", "inspection", "INSP-1", "2026-01-01", "2026-01-12", "pending", False, db_path
    )

    tracked = track_items("P-1", db_path=db_path)
    slippage = critical_path_slippage("P-1", "2026-01-15", db_path)

    assert tracked["count"] == 3
    assert slippage["count"] == 1
    assert slippage["open_critical_past_due"][0]["ref"] == "RFI-001"
    assert slippage["open_critical_past_due"][0]["days_late"] == 5
    assert "register-reported" in tracked["items"][0]["evidence_basis"]
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cx_%'"
            )
        }
    assert tables == {"cx_items"}


def test_draw_forecast_persists_penny_exact_owned_tables(tmp_path):
    db_path = tmp_path / "draws.db"
    result = forecast_draws(
        101,
        {"start": "2026-02", "months": 3, "curve": "s_curve"},
        project_id="P-2",
        db_path=db_path,
    )

    assert result["persistence"]["saved_draw_count"] == 3
    with sqlite3.connect(db_path) as connection:
        project_total = connection.execute(
            "SELECT budget_cents FROM cx_projects WHERE project_id='P-2'"
        ).fetchone()[0]
        draw_total = connection.execute(
            "SELECT SUM(projected_draw_cents) FROM cx_draws WHERE project_id='P-2'"
        ).fetchone()[0]
    assert project_total == draw_total == 101
