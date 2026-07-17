from __future__ import annotations

import pytest

from cre_mcp.fund.calls import forecast_capital_calls
from cre_mcp.fund.nav import (
    nav_report,
    record_fund_flow,
    record_fund_mark,
)


def test_capital_call_schedule_is_penny_exact_and_caps_at_unfunded(tmp_path):
    db_path = tmp_path / "fund.db"
    result = forecast_capital_calls(
        [
            {
                "month": "2026-08",
                "acquisitions_cents": 101,
                "capex_cents": 0,
                "reserves_cents": 0,
            },
            {
                "month": "2026-09",
                "acquisitions_cents": 100,
                "capex_cents": 25,
                "reserves_cents": 25,
            },
        ],
        [
            {"investor": "Alpha", "committed_cents": 100, "funded_cents": 0},
            {"investor": "Beta", "committed_cents": 100, "funded_cents": 0},
        ],
        gp_coinvest_pct=10,
        db_path=db_path,
    )

    august, september = result["schedule"]
    assert august["gp_coinvest_cents"] == 10
    assert [line["call_cents"] for line in august["investor_calls"]] == [46, 45]
    assert september["gp_coinvest_cents"] == 15
    assert [line["call_cents"] for line in september["investor_calls"]] == [54, 55]
    assert september["unfunded_gap_cents"] == 26
    assert result["totals_cents"] == {
        "gross_need": 251,
        "gp_coinvest": 25,
        "lp_calls": 200,
        "unfunded_gap": 26,
    }
    assert all(item["balance_check_cents"] == 0 for item in result["schedule"])
    assert all(
        item["projected_unfunded_cents"] == 0
        and item["projected_funded_cents"] == item["committed_cents"]
        for item in result["investor_tracking"]
    )
    assert all(item["commitment_id"] > 0 for item in result["investor_tracking"])
    assert result["default_remedy"]["status"] == "UNRESOLVED"
    assert "securities counsel" in result["counsel_flag"]

    alpha_id = result["investor_tracking"][0]["commitment_id"]
    forecast_capital_calls(
        [],
        [{"investor": "Alpha", "committed_cents": 100, "funded_cents": 0}],
        db_path=db_path,
    )
    refreshed = forecast_capital_calls([], commitments=None, db_path=db_path)
    assert [row["investor"] for row in refreshed["investor_tracking"]] == ["Alpha"]
    assert refreshed["investor_tracking"][0]["commitment_id"] == alpha_id


def test_nav_and_attribution_balance_exactly_from_governed_cents(tmp_path):
    db_path = tmp_path / "fund.db"
    prior = record_fund_mark(
        "Warehouse A",
        "2026-Q1",
        100_000,
        "cost",
        source_label="closing statement CS-1",
        db_path=db_path,
    )
    current = record_fund_mark(
        "Warehouse A",
        "2026-Q2",
        120_000,
        "appraisal",
        source_label="appraisal APP-22",
        db_path=db_path,
    )
    contribution = record_fund_flow(
        "2026-Q2",
        "contribution",
        50_000,
        investor="Alpha",
        source_label="bank trace BT-1",
        db_path=db_path,
    )
    distribution = record_fund_flow(
        "2026-Q2",
        "distribution",
        7_000,
        investor="Alpha",
        source_label="distribution ledger DL-1",
        attribution="income",
        db_path=db_path,
    )
    fee = record_fund_flow(
        "2026-Q2",
        "fee",
        1_000,
        investor="Alpha",
        source_label="fee ledger FL-1",
        db_path=db_path,
    )

    report = nav_report(
        "2026-Q2",
        cash_cents=10_000,
        liabilities_cents=5_000,
        cash_source="bank reconciliation BR-2",
        liabilities_source="administrator trial balance TB-2",
        fee_convention="invested",
        management_fee_bps=200,
        fee_period_months=3,
        fee_basis_cents=100_000,
        fee_basis_source="administrator invested capital schedule IC-2",
        management_fee_source="LPA section 8.2",
        db_path=db_path,
    )

    assert report["nav_cents"] == 125_000
    assert report["nav_formula"]["balance_check_cents"] == 0
    assert report["management_fee"]["calculated_accrual_cents"] == 500
    assert report["management_fee"]["terms_source"] == {
        "kind": "caller_input",
        "label": "LPA section 8.2",
    }
    assert report["management_fee"]["recorded_fee_cents"] == 1_000
    attribution = report["return_attribution"]
    assert attribution["income_cents"] == 7_000
    assert attribution["appreciation_cents"] == 20_000
    assert attribution["fees_cents"] == 1_000
    assert attribution["net_attributed_return_cents"] == 26_000
    assert attribution["sum_check_cents"] == 0
    assert report["capital_accounts"] == [
        {
            "investor": "Alpha",
            "contributions_cents": 50_000,
            "distributions_cents": 7_000,
            "fees_cents": 1_000,
            "net_cash_activity_cents": 42_000,
            "source_refs": [
                {"table": "fund_flows", "id": contribution["id"]},
                {"table": "fund_flows", "id": distribution["id"]},
                {"table": "fund_flows", "id": fee["id"]},
            ],
            "scope": (
                "Cash-activity capital-account statement only. NAV/profit/loss is not "
                "allocated because governing allocation rules were not supplied."
            ),
        }
    ]
    assert report["marks"][0]["source_ref"] == {
        "table": "fund_marks",
        "id": current["id"],
    }
    assert attribution["mark_changes"][0]["prior_source_ref"] == {
        "table": "fund_marks",
        "id": prior["id"],
    }


def test_nav_fails_closed_on_duplicate_marks_and_mixed_period_conventions(tmp_path):
    duplicate_db = tmp_path / "duplicates.db"
    for value in (100, 101):
        record_fund_mark(
            "Asset A",
            "2026-Q2",
            value,
            "model",
            source_label=f"model version {value}",
            db_path=duplicate_db,
        )
    with pytest.raises(ValueError, match="duplicate marks"):
        nav_report(
            "2026-Q2",
            0,
            0,
            cash_source="bank reconciliation",
            liabilities_source="trial balance",
            db_path=duplicate_db,
        )

    mixed_db = tmp_path / "mixed.db"
    record_fund_mark(
        "Asset A",
        "2026-Q2",
        100,
        "cost",
        source_label="closing statement",
        db_path=mixed_db,
    )
    record_fund_flow(
        "2026-06",
        "fee",
        1,
        source_label="monthly fee ledger",
        db_path=mixed_db,
    )
    with pytest.raises(ValueError, match="mixed YYYY-MM and YYYY-Q"):
        nav_report(
            "2026-Q2",
            0,
            0,
            cash_source="bank reconciliation",
            liabilities_source="trial balance",
            db_path=mixed_db,
        )


def test_negative_nav_is_reported_and_fee_terms_require_a_source(tmp_path):
    db_path = tmp_path / "negative.db"
    record_fund_mark(
        "Asset A",
        "2026-Q2",
        100,
        "cost",
        source_label="closing statement",
        db_path=db_path,
    )
    report = nav_report(
        "2026-Q2",
        0,
        101,
        cash_source="bank reconciliation",
        liabilities_source="administrator trial balance",
        db_path=db_path,
    )
    assert report["nav_cents"] == -1
    assert report["nav_formula"]["balance_check_cents"] == 0
    assert report["nav_status"] == "NEGATIVE NAV — DISTRESS/ADMINISTRATOR REVIEW REQUIRED"

    with pytest.raises(ValueError, match="management_fee_source"):
        nav_report(
            "2026-Q2",
            0,
            101,
            cash_source="bank reconciliation",
            liabilities_source="administrator trial balance",
            fee_convention="invested",
            management_fee_bps=200,
            fee_basis_cents=100,
            fee_basis_source="invested capital schedule",
            db_path=db_path,
        )


def test_capital_inputs_reject_performance_promises_and_trace_pipeline(tmp_path):
    with pytest.raises(ValueError, match="anti-fraud"):
        forecast_capital_calls(
            {
                "2026-08": {
                    "acquisitions_cents": 1,
                    "capex_cents": 0,
                    "reserves_cents": 0,
                    "note": "guaranteed return",
                }
            },
            [],
            db_path=tmp_path / "blocked.db",
        )

    result = forecast_capital_calls(
        {
            "2026-08": {
                "acquisitions_cents": 1,
                "capex_cents": 0,
                "reserves_cents": 0,
            }
        },
        [],
        db_path=tmp_path / "clear.db",
    )
    assert result["schedule"][0]["source_ref"] == {
        "kind": "caller_input",
        "field": "pipeline_needs",
        "index": 0,
    }
    assert "SCENARIOS, NOT PROMISES" in result["anti_fraud_warning"]
