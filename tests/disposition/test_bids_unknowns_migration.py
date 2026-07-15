"""Honest sparse-bid persistence, normalization, and owned-table migration."""

from __future__ import annotations

import inspect
import math
import sqlite3

import pytest

from cre_mcp.disposition import bids, tools
from cre_mcp.disposition.bids import normalize_bids, record_bid


def _adjustment(normalized_bid: dict, kind: str) -> dict:
    return next(
        adjustment
        for adjustment in normalized_bid["adjustments"]
        if adjustment["kind"] == kind
    )


def test_director_exact_probe_accepts_unknown_closing_days(disposition_db):
    result = tools.record_bid(
        "deal-director-probe",
        "buyer-director-probe",
        4_400_000,
        deposit=25_000,
        dd_days=60,
        contingencies=["inspection"],
        financing={"type": "bank", "proof": False},
    )

    assert "error" not in result
    assert result["deal_id"] == "deal-director-probe"
    assert result["buyer_id"] == "buyer-director-probe"
    assert result["price"] == 4_400_000
    assert result["closing_days"] is None


def test_price_only_bid_preserves_unknowns_and_normalizes_with_exposed_defaults(
    disposition_db,
):
    created = tools.record_bid(
        "deal-price-only",
        "buyer-price-only",
        5_000_000,
        bid_id="bid-price-only",
    )

    assert "error" not in created
    assert created["deposit"] is None
    assert created["dd_days"] is None
    assert created["closing_days"] is None
    assert created["contingencies"] is None
    assert created["financing"] is None
    assert created["received_at"] is None
    assert created["received_at_source"] == "unknown"

    with sqlite3.connect(disposition_db) as connection:
        stored = connection.execute(
            """
            SELECT deposit, dd_days, closing_days, contingencies, financing,
                   received_at
            FROM disp_bids WHERE bid_id='bid-price-only'
            """
        ).fetchone()
    assert stored == (None, None, None, None, None, None)

    result = tools.normalize_bids(
        "deal-price-only",
        carry_cost_per_day=1_000,
    )
    assert "error" not in result
    assert result["weights"]["unknown_dd_days_default"] == 60
    assert result["weights"]["unknown_closing_days_default"] == 45
    assert any("60" in convention and "dd_days" in convention for convention in result["conventions"])
    assert any("45" in convention and "closing_days" in convention for convention in result["conventions"])

    ranked = result["ranked_bids"][0]
    notes = " ".join(ranked["unknown_field_notes"]).casefold()
    for field in (
        "deposit",
        "dd_days",
        "closing_days",
        "contingencies",
        "financing",
        "received_at",
    ):
        assert field in notes

    deposit = _adjustment(ranked, "deposit_at_risk_credit")
    assert deposit["amount"] == 0
    assert deposit["inputs"] == {
        "stated_deposit": None,
        "deposit_at_risk": 0.0,
        "deposit_at_risk_source": "unknown deposit: weakest credit convention",
        "deposit_credit_rate": result["weights"]["deposit_credit_rate"],
        "value_source": "unknown_convention",
    }

    diligence = _adjustment(ranked, "dd_carry_cost")
    assert diligence["amount"] == -60_000
    assert diligence["inputs"]["stated_dd_days"] is None
    assert diligence["inputs"]["dd_days_used"] == 60
    assert diligence["inputs"]["value_source"] == "unknown_convention"

    closing = _adjustment(ranked, "closing_carry_cost")
    assert closing["amount"] == -45_000
    assert closing["inputs"]["stated_closing_days"] is None
    assert closing["inputs"]["closing_days_used"] == 45
    assert closing["inputs"]["value_source"] == "unknown_convention"

    financing = _adjustment(ranked, "financing_risk_haircut")
    assert financing["amount"] < 0
    assert financing["inputs"]["financing_type"] == "unknown"
    assert financing["inputs"]["proof"] is False
    assert financing["inputs"]["value_source"] == "unknown_convention"

    contingencies = _adjustment(ranked, "contingency_haircut")
    assert contingencies["amount"] < 0
    assert contingencies["inputs"]["value_source"] == "unknown_convention"
    assert contingencies["inputs"]["components"] == [
        {
            "contingency": "unknown",
            "category": "unknown",
            "rate": result["weights"]["contingency_haircuts"]["unknown"],
        }
    ]

    hand_adjusted = ranked["headline_price"] + sum(
        adjustment["amount"] for adjustment in ranked["adjustments"]
    )
    assert ranked["adjusted_price"] == pytest.approx(hand_adjusted)


def test_terms_only_retrade_preserves_unknown_price_and_resolves_once(
    disposition_db,
):
    created = tools.record_bid(
        "deal-terms-retrade",
        "buyer-terms-retrade",
        5_000_000,
        bid_id="bid-terms-retrade",
    )
    assert "error" not in created

    retraded = tools.record_bid(
        "deal-terms-retrade",
        "buyer-terms-retrade",
        5_000_000,
        deposit=75_000,
        dd_days=75,
        bid_id="bid-terms-retrade",
        status="retraded",
    )

    assert "error" not in retraded
    assert retraded["status"] == "retraded"
    assert retraded["deposit"] == 75_000
    assert retraded["dd_days"] == 75
    assert retraded["final_price"] is None
    assert retraded["retrade_delta_dollars"] is None
    assert retraded["retrade_delta_pct"] is None
    assert retraded["retrade"] is None
    assert retraded["retrade_count"] == 1
    assert retraded["buyer_behavior"]["retrades"] == 1
    assert retraded["outcome_transition"]["retrade_recorded"] is True
    assert len(retraded["retrade_history"]) == 1
    unresolved_event = retraded["retrade_history"][0]
    assert unresolved_event["from_price"] == 5_000_000
    assert unresolved_event["to_price"] is None
    assert unresolved_event["to_price_status"] == "unknown"
    assert unresolved_event["to_price_source"] == "not_reported"
    assert unresolved_event["trigger"] == "status_retraded"
    assert "unknown" in unresolved_event["note"].casefold()

    normalized = tools.normalize_bids(
        "deal-terms-retrade",
        carry_cost_per_day=100,
    )
    assert "error" not in normalized
    unresolved = normalized["ranked_bids"][0]
    assert unresolved["final_price"] is None
    assert unresolved["retrade_delta_dollars"] is None
    assert _adjustment(unresolved, "retrade_price_change")["amount"] == 0

    repeated = tools.record_bid(
        "deal-terms-retrade",
        "buyer-terms-retrade",
        5_000_000,
        bid_id="bid-terms-retrade",
        status="retraded",
    )
    assert "error" not in repeated
    assert repeated["retrade_count"] == 1
    assert len(repeated["retrade_history"]) == 1
    assert repeated["buyer_behavior"]["retrades"] == 1
    assert repeated["outcome_transition"]["retrade_recorded"] is False

    resolved = tools.record_bid(
        "deal-terms-retrade",
        "buyer-terms-retrade",
        5_000_000,
        bid_id="bid-terms-retrade",
        status="closed",
        final_price=4_700_000,
    )

    assert "error" not in resolved
    assert resolved["status"] == "closed"
    assert resolved["final_price"] == 4_700_000
    assert resolved["retrade_delta_dollars"] == -300_000
    assert resolved["retrade_delta_pct"] == pytest.approx(-0.06)
    assert resolved["retrade_count"] == 1
    assert resolved["buyer_behavior"]["retrades"] == 1
    assert resolved["buyer_behavior"]["closes"] == 1
    assert len(resolved["retrade_history"]) == 1
    resolution = resolved["retrade_history"][0]
    assert resolution["to_price"] == 4_700_000
    assert resolution["to_price_status"] in {"known", "reported"}
    assert resolution["to_price_source"] == "later_reported_resolution"
    assert "resolved" in resolution["note"].casefold()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("deposit", "garbage", "deposit must be numeric"),
        ("deposit", True, "deposit must be numeric"),
        ("deposit", math.nan, "deposit must be finite"),
        ("dd_days", "garbage", "dd_days must be numeric"),
        ("dd_days", False, "dd_days must be numeric"),
        ("dd_days", math.inf, "dd_days must be finite"),
        ("dd_days", 12.5, "dd_days must be a whole number"),
        ("closing_days", "garbage", "closing_days must be numeric"),
        ("closing_days", True, "closing_days must be numeric"),
        ("closing_days", -math.inf, "closing_days must be finite"),
        ("closing_days", 21.25, "closing_days must be a whole number"),
    ],
)
def test_optional_bid_terms_reject_supplied_garbage(
    disposition_db, field, value, message
):
    payload = {
        "bid_id": f"invalid-{field}",
        "deal_id": "deal-invalid",
        "buyer_id": "buyer-invalid",
        "price": 1_000_000,
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        record_bid(payload, db_path=disposition_db)


@pytest.mark.parametrize(
    ("price", "message"),
    [
        ("garbage", "price must be numeric"),
        (True, "price must be numeric"),
        (math.nan, "price must be finite"),
        (math.inf, "price must be finite"),
    ],
)
def test_required_price_still_rejects_garbage(disposition_db, price, message):
    result = tools.record_bid("deal-invalid-price", "buyer-invalid-price", price)

    assert result == {"error": message}


def test_v1_not_null_table_migrates_rows_indexes_and_nullable_constraints(
    disposition_db,
):
    with sqlite3.connect(disposition_db) as connection:
        connection.executescript(
            """
            CREATE TABLE unrelated_sentinel (
                sentinel_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE INDEX idx_unrelated_sentinel_payload
                ON unrelated_sentinel(payload);
            INSERT INTO unrelated_sentinel VALUES ('keep-me', 'untouched');

            CREATE TABLE disp_bids (
                bid_id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL,
                buyer_id TEXT NOT NULL,
                price REAL NOT NULL,
                deposit REAL NOT NULL,
                dd_days INTEGER NOT NULL,
                closing_days INTEGER NOT NULL,
                contingencies TEXT NOT NULL DEFAULT '[]',
                financing TEXT NOT NULL DEFAULT '{}',
                received_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                final_price REAL,
                retrade_count INTEGER NOT NULL DEFAULT 0,
                retrade_history TEXT NOT NULL DEFAULT '[]',
                status_changed_at TEXT NOT NULL,
                CHECK(price > 0),
                CHECK(deposit >= 0),
                CHECK(dd_days >= 0),
                CHECK(closing_days >= 0),
                CHECK(status IN ('active', 'retraded', 'withdrawn', 'selected', 'closed')),
                CHECK(final_price IS NULL OR final_price > 0),
                CHECK(retrade_count >= 0)
            );
            CREATE INDEX idx_disp_bids_deal_status
                ON disp_bids(deal_id, status, received_at);
            CREATE INDEX idx_disp_bids_buyer
                ON disp_bids(buyer_id, received_at);
            CREATE INDEX idx_disp_bids_custom_price
                ON disp_bids(price DESC);
            INSERT INTO disp_bids VALUES (
                'legacy-bid', 'legacy-deal', 'legacy-buyer', 4200000,
                100000, 30, 20, '["inspection"]',
                '{"type":"bank","proof":true}',
                '2026-07-01T12:00:00+00:00', 'active', NULL, 0, '[]',
                '2026-07-01T12:00:00+00:00'
            );
            """
        )

    created = record_bid(
        {
            "bid_id": "sparse-after-migration",
            "deal_id": "new-deal",
            "buyer_id": "new-buyer",
            "price": 3_300_000,
        },
        db_path=disposition_db,
    )
    assert created["deposit"] is None

    with sqlite3.connect(disposition_db) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(disp_bids)")
        }
        for field in (
            "deposit",
            "dd_days",
            "closing_days",
            "contingencies",
            "financing",
            "received_at",
        ):
            assert columns[field]["notnull"] == 0

        legacy = connection.execute(
            "SELECT * FROM disp_bids WHERE bid_id='legacy-bid'"
        ).fetchone()
        assert dict(legacy) == {
            "bid_id": "legacy-bid",
            "deal_id": "legacy-deal",
            "buyer_id": "legacy-buyer",
            "price": 4_200_000.0,
            "deposit": 100_000.0,
            "dd_days": 30,
            "closing_days": 20,
            "contingencies": '["inspection"]',
            "financing": '{"type":"bank","proof":true}',
            "received_at": "2026-07-01T12:00:00+00:00",
            "status": "active",
            "final_price": None,
            "retrade_count": 0,
            "retrade_history": "[]",
            "status_changed_at": "2026-07-01T12:00:00+00:00",
        }

        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_disp_bids_deal_status" in indexes
        assert "idx_disp_bids_buyer" in indexes
        assert "idx_disp_bids_custom_price" in indexes
        assert "idx_unrelated_sentinel_payload" in indexes
        sentinel = connection.execute(
            "SELECT sentinel_id, payload FROM unrelated_sentinel"
        ).fetchone()
        assert tuple(sentinel) == ("keep-me", "untouched")


def test_schema_migration_does_not_use_executescript_inside_transaction():
    source = inspect.getsource(bids._ensure_schema)

    assert "executescript" not in source
