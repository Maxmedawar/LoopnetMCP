"""Adversarial acceptance tests for financing execution operations."""

from __future__ import annotations

import sqlite3

from cre_mcp.finops.hedges import cap_cost_context
from cre_mcp.finops.notechain import reconcile_note_chain
from cre_mcp.finops.reporting import record_reporting_item, reporting_calendar
from cre_mcp.finops.waivers import prepare_waiver_request


def test_cap_cost_is_an_integer_cent_range_with_convention_and_live_quote_warning():
    result = cap_cost_context(
        {"balance_cents": 25_000_001, "index": 0.04, "spread_bps": 275},
        {"strike": 0.05, "term_years": 2},
    )

    assert "error" not in result
    assert result["cost_range_cents"]["low"] <= result["cost_range_cents"]["high"]
    assert all(
        isinstance(result["cost_range_cents"][bound], int)
        for bound in ("low", "high")
    )
    assert "convention" in str(result["citation"]).casefold()
    assert "licensed provider" in result["live_quote_warning"].casefold()
    assert result["convention_grid"]
    escrow = result["escrow"]
    assert escrow["months"] == 24
    assert all(
        isinstance(escrow["monthly_range_cents"][bound], int)
        for bound in ("low", "high")
    )


def test_waiver_request_memo_assembles_facts_cause_cure_ask_and_review_flags():
    result = prepare_waiver_request(
        {
            "loan": "Commerce Center senior",
            "lender": "Example Bank",
            "balance_cents": 12_345_678_901,
            "cause": "Anchor tenant vacated during the test period.",
            "cure_plan": "Signed replacement LOI and a 90-day interest reserve.",
        },
        {
            "status": "projected",
            "periods": [
                {
                    "period": "2026-Q3",
                    "dscr": 1.12,
                    "minimum_dscr": 1.25,
                    "breaches": ["minimum DSCR"],
                }
            ],
        },
        {
            "type": "waiver",
            "terms": "Waive the 2026-Q3 DSCR test without changing economics.",
        },
    )

    assert "error" not in result
    memo = result["memo"]
    assert memo["loan_facts"]["loan"] == "Commerce Center senior"
    assert memo["covenant_test_results"]["periods"][0]["period"] == "2026-Q3"
    assert "Anchor tenant" in str(memo["cause"])
    assert "replacement LOI" in str(memo["cure_plan"])
    assert memo["request"]["type"] == "waiver"
    assert "2026-Q3" in str(memo["request"])
    assert "counsel" in result["counsel_flag"].casefold()
    assert "lender_track_record" in result["lender_history_note"]


def test_reporting_calendar_has_inclusive_sixty_day_window_and_omits_closed_items(
    tmp_path,
):
    db_path = tmp_path / "reporting.db"
    record_reporting_item(
        "Loan A", "July rent roll", "monthly", "2026-07-14", "servicer@example.test", db_path=db_path
    )
    record_reporting_item(
        "Loan A", "Quarterly compliance", "quarterly", "2026-09-12", "Bank", db_path=db_path
    )
    record_reporting_item(
        "Loan A", "Outside window", "annual", "2026-09-13", "Bank", db_path=db_path
    )
    record_reporting_item(
        "Loan A", "Already delivered", "monthly", "2026-07-20", "Bank", status="complete", db_path=db_path
    )

    result = reporting_calendar(days=60, db_path=db_path, as_of="2026-07-14")

    assert result["as_of"] == "2026-07-14"
    assert result["through"] == "2026-09-12"
    assert [item["item"] for item in result["deliverables"]] == [
        "July rent roll",
        "Quarterly compliance",
    ]
    assert result["count"] == 2
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM fo_reporting"
        ).fetchone()[0] == 4


def test_note_chain_reports_exact_assignment_break_and_curative_counsel_flag():
    result = reconcile_note_chain(
        [
            {
                "kind": "note",
                "from_party": "Borrower LLC",
                "to_party": "Originator LLC",
                "date": "2024-01-01",
            },
            {
                "kind": "assignment",
                "from_party": "Originator LLC",
                "to_party": "Warehouse SPV",
                "date": "2024-02-01",
                "recorded": True,
            },
            {
                "kind": "assignment",
                "from_party": "Unrelated Depositor",
                "to_party": "Securitization Trust",
                "date": "2024-03-01",
                "recorded": True,
            },
            {
                "kind": "allonge",
                "from_party": "Originator LLC",
                "to_party": "Warehouse SPV",
                "date": "2024-02-01",
            },
            {
                "kind": "allonge",
                "from_party": "Warehouse SPV",
                "to_party": "Securitization Trust",
                "date": "2024-03-01",
            },
            {
                "kind": "mortgage",
                "to_party": "Originator LLC",
                "date": "2024-01-01",
                "recorded": True,
            },
        ]
    )

    assert "error" not in result
    assert len(result["breaks"]) == 1
    broken_link = result["breaks"][0]
    assert broken_link["expected_from_party"] == "Warehouse SPV"
    assert broken_link["actual_from_party"] == "Unrelated Depositor"
    assert result["endorsement_continuity"]["continuous"] is True
    assert result["curative_work_needed"] is True
    assert "curative work needed" in result["counsel_flag"].casefold()
    assert "counsel" in result["counsel_flag"].casefold()
