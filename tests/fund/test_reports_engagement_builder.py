"""Adversarial governed-reporting and engagement-honesty tests."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.fund.engagement import engagement_report, record_investor_touch
from cre_mcp.fund.reports import quarterly_investor_report


def _create_governed_fund_rows(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE fund_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                period TEXT NOT NULL,
                value_cents INTEGER NOT NULL,
                source TEXT NOT NULL
            );
            CREATE TABLE fund_flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                type TEXT NOT NULL,
                cents INTEGER NOT NULL
            );
            CREATE TABLE fund_commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                investor TEXT NOT NULL,
                committed_cents INTEGER NOT NULL,
                funded_cents INTEGER NOT NULL
            );
            INSERT INTO fund_marks(asset, period, value_cents, source) VALUES
                ('Mesa Shops', '2026-Q2', 100000001, 'appraisal'),
                ('Lake Offices', '2026-Q2', 25000002, 'broker_opinion'),
                ('Old Period', '2026-Q1', 999999999, 'cost');
            INSERT INTO fund_flows(period, type, cents) VALUES
                ('2026-Q2', 'contribution', 1000003),
                ('2026-Q2', 'distribution', 333335),
                ('2026-Q2', 'fee', 10001),
                ('2026-Q1', 'distribution', 9000000);
            INSERT INTO fund_commitments(investor, committed_cents, funded_cents) VALUES
                ('LP One', 1500001, 500001),
                ('LP Two', 2500002, 1000001);
            """
        )


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_quarterly_report_is_penny_exact_and_every_amount_has_row_sources(tmp_path):
    path = tmp_path / "fund.db"
    _create_governed_fund_rows(path)

    report = quarterly_investor_report("2026-Q2", db_path=path)
    figures = {figure["key"]: figure for figure in report["figures"]}

    assert figures["gross_asset_marks_cents"]["value_cents"] == 125000003
    assert figures["period_contribution_cents"]["value_cents"] == 1000003
    assert figures["period_distribution_cents"]["value_cents"] == 333335
    assert figures["period_fee_cents"]["value_cents"] == 10001
    assert figures["total_committed_cents"]["value_cents"] == 4000003
    assert figures["total_funded_cents"]["value_cents"] == 1500002
    assert figures["gross_asset_marks_cents"]["display"] == "$1,250,000.03"
    assert {ref["id"] for ref in figures["gross_asset_marks_cents"]["source_refs"]} == {1, 2}
    assert all(ref["table"] == "fund_marks" for ref in figures["gross_asset_marks_cents"]["source_refs"])

    amount_objects = [node for node in _walk(report) if "value_cents" in node]
    assert amount_objects
    for amount in amount_objects:
        assert amount["source_refs"]
        assert all(source.get("table") and source.get("id") is not None for source in amount["source_refs"])

    assert "999999999" not in str(report)
    assert any("NAV is not stated" in item for item in report["unanswered_questions"])
    assert "HARD GATE" in report["guardrail"]


def test_quarterly_narrative_is_fixed_fact_template_with_fact_provenance(tmp_path):
    path = tmp_path / "fund.db"
    _create_governed_fund_rows(path)

    report = quarterly_investor_report("2026-Q2", db_path=path)

    assert report["narrative"]
    for paragraph in report["narrative"]:
        assert paragraph["template_id"].startswith("governed_")
        assert paragraph["facts"]
        for fact in paragraph["facts"]:
            assert fact["source_refs"]
            assert all(ref["table"] and ref["id"] is not None for ref in fact["source_refs"])
    narrative_text = " ".join(item["text"] for item in report["narrative"]).casefold()
    for invented_claim in ("outperform", "strong quarter", "on track", "expected return"):
        assert invented_claim not in narrative_text


def test_quarterly_report_does_not_create_or_zero_fill_absent_sources(tmp_path):
    missing_path = tmp_path / "missing.db"
    missing = quarterly_investor_report("2026-Q2", db_path=missing_path)

    assert not missing_path.exists()
    assert missing["figures"] == []
    assert missing["narrative"] == []
    assert missing["portfolio_marks"] == []
    assert any("does not exist" in item for item in missing["unanswered_questions"])

    empty_path = tmp_path / "empty.db"
    with sqlite3.connect(empty_path):
        pass
    empty = quarterly_investor_report("2026-Q2", db_path=empty_path)
    with sqlite3.connect(empty_path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert empty["figures"] == []
    assert empty["narrative"] == []
    assert tables == []
    assert all("zero" in item for item in empty["unanswered_questions"] if "unavailable" in item)


def test_quarterly_report_refuses_performance_guarantee_language(tmp_path):
    with pytest.raises(ValueError, match="anti-fraud"):
        quarterly_investor_report("guaranteed return period", db_path=tmp_path / "x.db")


def test_engagement_distinguishes_activity_from_delivery_and_is_uncalibrated(tmp_path):
    path = tmp_path / "ir.db"
    first = record_investor_touch(
        "LP One", "call", "2026-06-30T00:00:00Z", "Portfolio questions", db_path=path
    )
    second = record_investor_touch(
        "LP One", "email", "2026-06-10T00:00:00Z", db_path=path
    )
    delivered = record_investor_touch(
        "LP One", "report", "2026-07-01T00:00:00Z", db_path=path
    )
    report = engagement_report(
        "LP One", as_of="2026-07-10T00:00:00Z", db_path=path
    )
    investor = report["investors"][0]

    assert first["source_ref"] == {"table": "ir_touches", "id": 1}
    assert second["source_ref"]["id"] == 2
    assert delivered["source_ref"]["id"] == 3
    assert investor["interactive_touch_count"]["value"] == 2
    assert investor["delivery_event_count"]["value"] == 1
    assert investor["recency_days"]["value"] == 9
    assert investor["re_up_likelihood"]["label"] == "moderate recorded-activity signal"
    assert investor["re_up_likelihood"]["heuristic_score"]["value"] == 60
    assert len(investor["re_up_likelihood"]["source_refs"]) == 2
    assert "UNCALIBRATED" in report["honesty"]
    assert "not a probability" in report["honesty"]
    assert "HARD GATE" in report["guardrail"]


def test_delivery_only_touch_does_not_create_predictive_score(tmp_path):
    path = tmp_path / "ir.db"
    record_investor_touch(
        "LP Delivery", "distribution", "2026-06-01T00:00:00Z", db_path=path
    )

    report = engagement_report(
        "LP Delivery", as_of="2026-07-10T00:00:00Z", db_path=path
    )
    re_up = report["investors"][0]["re_up_likelihood"]

    assert re_up["label"] == "insufficient governed interactive activity"
    assert "heuristic_score" not in re_up
    assert re_up["source_refs"] == []


def test_engagement_empty_filter_infers_nothing_and_store_owns_only_touch_table(tmp_path):
    path = tmp_path / "ir.db"
    report = engagement_report(
        "Unknown LP", as_of="2026-07-10T00:00:00Z", db_path=path
    )
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert report["investors"] == []
    assert report["unanswered_questions"]
    assert "no engagement or re-up label was inferred" in report["unanswered_questions"][0]
    assert tables == {"ir_touches"}


@pytest.mark.parametrize(
    ("investor", "touch_type", "note", "message"),
    [
        ("", "call", None, "investor cannot be blank"),
        ("LP One", "text", None, "type must be one of"),
        ("LP One", "email", "Return is guaranteed", "anti-fraud"),
        ("LP One", "email", "This is risk-free", "anti-fraud"),
    ],
)
def test_engagement_boundary_and_anti_fraud_rejections(
    tmp_path, investor, touch_type, note, message
):
    path = tmp_path / "ir.db"
    with pytest.raises(ValueError, match=message):
        record_investor_touch(
            investor,
            touch_type,
            "2026-01-01T00:00:00Z",
            note,
            db_path=path,
        )
    if path.exists():
        with sqlite3.connect(path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ir_touches'"
            ).fetchone()
            count = (
                connection.execute("SELECT COUNT(*) FROM ir_touches").fetchone()[0]
                if exists
                else 0
            )
        assert count == 0
