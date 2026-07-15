"""Buyer-universe and certainty-adjusted bid contracts."""

import pytest

from cre_mcp.disposition.bids import normalize_bids, record_bid
from cre_mcp.disposition.buyers import match_buyers, record_buyer


def _buyer(buyer_id, name, *, low, high, geographies, asset_types, db_path):
    return record_buyer(
        {
            "buyer_id": buyer_id,
            "name": name,
            "type": "institutional",
            "check_size_min": low,
            "check_size_max": high,
            "geographies": geographies,
            "asset_types": asset_types,
            "financing_style": "all_cash",
            "source": "fixture",
            "notes": "QA fixture",
        },
        db_path=db_path,
    )


def test_buyer_matching_ranks_exact_fit_and_does_not_invent_behavior(disposition_db):
    _buyer(
        "buyer-exact",
        "Exact Capital",
        low=5_000_000,
        high=15_000_000,
        geographies=["Los Angeles"],
        asset_types=["retail"],
        db_path=disposition_db,
    )
    _buyer(
        "buyer-too-small",
        "Small Capital",
        low=500_000,
        high=2_000_000,
        geographies=["Phoenix"],
        asset_types=["industrial"],
        db_path=disposition_db,
    )

    result = match_buyers(
        {"price": 10_000_000, "type": "retail", "market": "Los Angeles"},
        db_path=disposition_db,
    )
    matches = result["matches"]

    assert matches[0]["buyer_id"] == "buyer-exact"
    assert matches[0]["fit_score"] > matches[1]["fit_score"]
    reasons = " ".join(matches[0]["fit_reasons"]).casefold()
    assert "check" in reasons and "geograph" in reasons and "asset" in reasons
    assert matches[0]["bids_made"] == 0
    assert matches[0]["retrades"] == 0
    assert matches[0]["closes"] == 0
    assert matches[0]["behavioral_history_status"] == "empty"
    assert matches[0]["behavioral_score"] is None
    assert (
        matches[0]["behavior_note"]
        == "no behavioral history yet — accrues via record_bid outcomes"
    )


def test_cleaner_lower_bid_wins_and_every_adjustment_reconciles(disposition_db):
    _buyer(
        "buyer-risky",
        "Risky Capital",
        low=1_000_000,
        high=20_000_000,
        geographies=["Dallas"],
        asset_types=["industrial"],
        db_path=disposition_db,
    )
    _buyer(
        "buyer-clean",
        "Clean Capital",
        low=1_000_000,
        high=20_000_000,
        geographies=["Dallas"],
        asset_types=["industrial"],
        db_path=disposition_db,
    )
    record_bid(
        {
            "bid_id": "bid-risky",
            "deal_id": "deal-normalize",
            "buyer_id": "buyer-risky",
            "price": 10_000_000,
            "deposit": 50_000,
            "dd_days": 90,
            "closing_days": 45,
            "contingencies": ["financing", "inspection"],
            "financing": {"type": "unknown", "proof": False},
            "received_at": "2026-07-14T12:00:00+00:00",
            "status": "active",
        },
        db_path=disposition_db,
    )
    record_bid(
        {
            "bid_id": "bid-clean",
            "deal_id": "deal-normalize",
            "buyer_id": "buyer-clean",
            "price": 9_500_000,
            "deposit": 750_000,
            "dd_days": 10,
            "closing_days": 20,
            "contingencies": [],
            "financing": {"type": "cash", "proof": True},
            "received_at": "2026-07-14T12:05:00+00:00",
            "status": "active",
        },
        db_path=disposition_db,
    )

    result = normalize_bids(
        "deal-normalize",
        carry_cost_per_day=20_000,
        db_path=disposition_db,
    )
    ranked = result["ranked_bids"]

    assert ranked[0]["bid_id"] == "bid-clean"
    assert result["weights"]["carry_cost_per_day"] == 20_000
    assert result["weights"]["financing_risk_weights"]
    assert result["weights"]["contingency_haircuts"]
    assert result["conventions"]

    for bid in ranked:
        adjustments = bid["adjustments"]
        assert adjustments
        # The implementation exposes a signed dollar amount for every adjustment:
        # positive amounts add to proceeds and negative amounts reduce them.
        hand_adjusted = bid["headline_price"] + sum(
            item["amount"] for item in adjustments
        )
        assert bid["adjusted_price"] == pytest.approx(hand_adjusted)
        assert {item["kind"] for item in adjustments} >= {
            "deposit_at_risk_credit",
            "dd_carry_cost",
            "financing_risk_haircut",
            "contingency_haircut",
        }


def test_retrade_update_preserves_one_bid_and_computes_delta(disposition_db):
    _buyer(
        "buyer-retrade",
        "Retrade Capital",
        low=1_000_000,
        high=20_000_000,
        geographies=["Denver"],
        asset_types=["office"],
        db_path=disposition_db,
    )
    original = {
        "bid_id": "bid-retrade",
        "deal_id": "deal-retrade",
        "buyer_id": "buyer-retrade",
        "price": 8_000_000,
        "deposit": 200_000,
        "dd_days": 30,
        "closing_days": 30,
        "contingencies": [],
        "financing": {"type": "bank", "proof": True},
        "received_at": "2026-07-10T12:00:00+00:00",
        "status": "active",
    }
    record_bid(original, db_path=disposition_db)
    record_bid(
        {"bid_id": "bid-retrade", "status": "retraded", "final_price": 7_600_000},
        db_path=disposition_db,
    )

    normalized = normalize_bids("deal-retrade", db_path=disposition_db)
    retraded = normalized["ranked_bids"][0]
    match = match_buyers(
        {"price": 8_000_000, "type": "office", "market": "Denver"},
        db_path=disposition_db,
    )["matches"][0]

    assert retraded["headline_price"] == 8_000_000
    assert retraded["final_price"] == 7_600_000
    assert retraded["retrade_delta_dollars"] == -400_000
    assert retraded["retrade_delta_pct"] == pytest.approx(-0.05)
    assert match["bids_made"] == 1
    assert match["retrades"] == 1
    assert match["closes"] == 0

    closed = record_bid(
        {"bid_id": "bid-retrade", "status": "closed", "final_price": 7_600_000},
        db_path=disposition_db,
    )
    closed_match = match_buyers(
        {"price": 8_000_000, "type": "office", "market": "Denver"},
        db_path=disposition_db,
    )["matches"][0]
    assert closed["retrade_count"] == 1
    assert closed_match["bids_made"] == 1
    assert closed_match["retrades"] == 1
    assert closed_match["closes"] == 1
