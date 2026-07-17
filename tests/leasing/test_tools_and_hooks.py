from __future__ import annotations

from cre_mcp.leasing import tools
from cre_mcp.leasing.prospects import tenant_prospect_list
from cre_mcp.leasing.watch import record_tenant_signal


def test_plain_tool_boundaries_return_error_objects() -> None:
    assert "error" in tools.tenant_sales_capacity("unknown", {}, {"sf": 1_000})
    assert "error" in tools.opening_critical_path({})
    assert "error" in tools.compare_lease_proposals([], {"sf": 1_000})


def test_prospect_ranking_exposes_watch_signal_hook(tmp_path) -> None:
    db_path = tmp_path / "watch.db"
    record_tenant_signal(
        "Starbucks",
        "coffee",
        "closure_news",
        "high",
        "Structured closure input for review",
        "2026-01-01",
        db_path=db_path,
    )

    result = tenant_prospect_list(
        {
            "sf": 2_200,
            "has_drive_thru": True,
            "demographics": {
                "population": 60_000,
                "median_income": 85_000,
                "traffic_aadt": 35_000,
            },
            "watch_db_path": db_path,
        },
        existing_cotenancy=[{"brand": "Whole Foods", "category": "grocery"}],
    )

    starbucks = next(row for row in result["prospects"] if row["brand"] == "Starbucks")
    assert starbucks["signal_count"] == 1
    assert starbucks["watch_adjustment"] < 0
    assert "closure_news/high" in starbucks["watch_adjustment_reasons"][0]
    assert "later phase" in result["watch_hook_note"]
