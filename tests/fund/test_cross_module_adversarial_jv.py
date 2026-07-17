"""Cross-module schema and governed-source adversarial checks."""

from cre_mcp.fund import tools
from cre_mcp.fund.calls import forecast_capital_calls
from cre_mcp.fund.nav import nav_report, record_fund_flow, record_fund_mark
from cre_mcp.fund.reports import quarterly_investor_report


def test_actual_owned_tables_interoperate_without_losing_source_ids(tmp_path):
    path = tmp_path / "fund.db"
    calls = forecast_capital_calls(
        [{"month": "2026-07", "acquisitions_cents": 0}],
        [
            {"investor": "LP A", "committed_cents": 10_001, "funded_cents": 1},
            {"investor": "LP B", "committed_cents": 20_002, "funded_cents": 2},
        ],
        db_path=path,
    )
    mark = record_fund_mark(
        "Asset A",
        "2026-Q2",
        100_003,
        "appraisal",
        source_label="appraisal APP-9",
        db_path=path,
    )
    flow = record_fund_flow(
        "2026-Q2",
        "contribution",
        5_005,
        investor="LP A",
        source_label="bank trace BT-9",
        db_path=path,
    )

    nav = nav_report(
        "2026-Q2",
        cash_cents=7,
        liabilities_cents=3,
        cash_source="bank reconciliation BR-9",
        liabilities_source="trial balance TB-9",
        fee_convention="committed",
        management_fee_bps=200,
        fee_period_months=3,
        management_fee_source="LPA section 6.1",
        db_path=path,
    )
    report = quarterly_investor_report("2026-Q2", db_path=path)
    figures = {item["key"]: item for item in report["figures"]}

    commitment_ids = [item["commitment_id"] for item in calls["investor_tracking"]]
    assert nav["management_fee"]["basis_cents"] == 30_003
    assert nav["management_fee"]["calculated_accrual_cents"] == 150
    assert nav["management_fee"]["basis_sources"] == [
        {"table": "fund_commitments", "id": commitment_id}
        for commitment_id in commitment_ids
    ]
    assert nav["nav_cents"] == 100_007
    mark_ref = figures["gross_asset_marks_cents"]["source_refs"][0]
    assert mark_ref["table"] == "fund_marks"
    assert mark_ref["id"] == mark["id"]
    assert "source_label" in mark_ref["columns"]
    assert figures["period_contribution_cents"]["source_refs"][0]["id"] == flow["id"]
    assert figures["total_committed_cents"]["value_cents"] == 30_003


def test_plain_nav_boundary_forwards_management_fee_term_source(tmp_path):
    path = tmp_path / "fund.db"
    tools.forecast_capital_calls(
        [{"month": "2026-07", "acquisitions_cents": 0}],
        [{"investor": "LP A", "committed_cents": 10_000, "funded_cents": 0}],
        db_path=path,
    )
    tools.record_fund_mark(
        "Asset A",
        "2026-Q2",
        100_000,
        "cost",
        source_label="closing statement CS-4",
        db_path=path,
    )

    report = tools.nav_report(
        "2026-Q2",
        0,
        0,
        cash_source="bank reconciliation BR-4",
        liabilities_source="trial balance TB-4",
        management_fee_bps=200,
        management_fee_source="LPA section 6.1",
        db_path=path,
    )

    assert "error" not in report
    assert report["management_fee"]["terms_source"]["label"] == "LPA section 6.1"
    assert report["management_fee"]["calculated_accrual_cents"] == 50
