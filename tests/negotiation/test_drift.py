"""Contract tests for structured, quote-backed LOI term drift detection."""

from __future__ import annotations

import json

import pytest

from cre_mcp.negotiation.drift import detect_term_drift


def _term_results(report: dict) -> list[dict]:
    results = report.get("term_results", report.get("terms"))
    assert isinstance(results, list), "drift output must expose per-term results"
    return results


def _by_term(report: dict) -> dict[str, dict]:
    return {str(row["term"]): row for row in _term_results(report)}


def test_changed_deposit_quotes_agreed_and_draft_versions() -> None:
    agreed = {
        "price": 5_000_000,
        "deposit": 100_000,
        "dd_days": 30,
        "closing_days": 45,
        "contingencies": ["inspection", "financing"],
    }
    draft = """
        PURCHASE AND SALE AGREEMENT
        Purchase Price: $5,000,000.
        Initial Deposit: $150,000.
        Buyer has 30 days for due diligence.
        Closing shall occur 45 days after the Effective Date.
        This Agreement is contingent on inspection and financing approval.
    """

    report = detect_term_drift(agreed, draft)
    deposit = _by_term(report)["deposit"]

    assert deposit["status"] == "changed"
    assert deposit["agreed_value"] == 100_000
    assert deposit["draft_value"] == 150_000
    assert "100" in deposit["agreed_quote"]
    assert "150" in deposit["draft_quote"]
    # Quotes must be distinct representations of the two versions, not one
    # quote reused twice and mislabeled as comparison evidence.
    assert deposit["agreed_quote"] != deposit["draft_quote"]
    assert deposit["severity"] in {"material", "fatal"}


def test_silently_dropped_contingency_is_fatal_and_routes_to_counsel() -> None:
    agreed = {
        "price": 5_000_000,
        "deposit": 100_000,
        "dd_days": 30,
        "closing_days": 45,
        "contingencies": ["inspection", "financing"],
    }
    # Inspection appears; financing is not mentioned anywhere in the draft.
    draft = """
        PURCHASE AND SALE AGREEMENT
        Purchase Price: $5,000,000. Initial Deposit: $100,000.
        Buyer has 30 days for due diligence and an inspection contingency.
        Closing shall occur 45 days after the Effective Date.
    """

    report = detect_term_drift(agreed, draft)
    rows = _by_term(report)
    financing = next(
        row
        for key, row in rows.items()
        if "financing" in key.casefold()
    )

    assert financing["status"] == "silent"
    assert financing["severity"] == "fatal"
    assert "financ" in financing["agreed_quote"].casefold()
    assert financing["draft_quote"] is None

    rendered = json.dumps(report, sort_keys=True).casefold()
    assert "counsel" in rendered
    assert "silence" in rendered and ("kill" in rendered or "eliminat" in rendered)
    assert "full-psa" in rendered or "full psa" in rendered
    assert "not attempted" in rendered or "targeted" in rendered


def test_matching_terms_include_the_actual_draft_quote() -> None:
    report = detect_term_drift(
        {"price": 2_250_000, "deposit": 50_000, "contingencies": []},
        "The Purchase Price is $2,250,000 and the Deposit is $50,000.",
    )
    rows = _by_term(report)

    assert rows["price"]["status"] == "matched"
    assert "$2,250,000" in rows["price"]["draft_quote"]
    assert rows["deposit"]["status"] == "matched"


@pytest.mark.parametrize(
    "waiver",
    [
        "Buyer waives any financing contingency.",
        "There shall be no financing contingency.",
    ],
)
def test_explicit_financing_waiver_is_changed_fatal_not_a_keyword_match(
    waiver: str,
) -> None:
    report = detect_term_drift(
        {"price": 1_000_000, "contingencies": ["financing"]},
        f"Purchase Price: $1,000,000. {waiver}",
    )
    row = next(
        row
        for row in _term_results(report)
        if "financing" in str(row["term"]).casefold()
    )

    assert row["status"] == "changed"
    assert row["severity"] == "fatal"
    assert "financ" in row["agreed_quote"].casefold()
    assert waiver.casefold().rstrip(".") in row["draft_quote"].casefold()


def test_targeted_patterns_handle_parenthetical_days_without_unrelated_money() -> None:
    report = detect_term_drift(
        {
            "price": 2_000_000,
            "deposit": 75_000,
            "dd_days": 30,
            "closing_days": 45,
            "contingencies": [],
        },
        """
        Purchase Price: $2,000,000. Brokerage commission: $75,000.
        Deposit: $60,000. The Due Diligence Period shall be thirty (30)
        calendar days. Closing shall occur within 45 days.
        """,
    )
    rows = _by_term(report)

    assert rows["deposit"]["status"] == "changed"
    assert rows["deposit"]["draft_value"] == 60_000
    assert "$60,000" in rows["deposit"]["draft_quote"]
    assert rows["dd_days"]["status"] == "matched"
    assert rows["closing_days"]["status"] == "matched"


def test_unknown_structured_key_is_reported_as_unsupported_not_silently_dropped() -> None:
    report = detect_term_drift(
        {"price": 1_000_000, "rofr": True, "contingencies": []},
        "Purchase Price is $1,000,000.",
    )
    rows = _by_term(report)

    assert "rofr" in rows
    assert rows["rofr"]["status"] in {"unsupported", "silent"}
    assert rows["rofr"]["agreed_quote"]
    assert rows["rofr"]["draft_quote"] is None
