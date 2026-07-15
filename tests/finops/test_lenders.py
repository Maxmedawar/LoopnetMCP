"""Persistence, fit reasoning, and appetite-staleness tests."""

import sqlite3

from cre_mcp.finops.lenders import match_lenders, record_lender_profile


def test_lender_match_is_fit_ranked_and_warns_when_appetite_is_stale(tmp_path):
    db_path = tmp_path / "lenders.db"
    recorded = record_lender_profile(
        {
            "name": "Legacy Regional Bank",
            "type": "bank",
            "geographies": ["CA", "AZ"],
            "asset_types": ["industrial", "multifamily"],
            "size_min": 500_000_000,
            "size_max": 2_000_000_000,
            "leverage_max": 0.75,
            "rate_context": None,
            "last_confirmed": "2025-01-01",
            "source": "2025 lender call notes",
        },
        db_path=db_path,
    )
    assert recorded["lender_id"] > 0
    assert recorded["rate_context"] is None

    result = match_lenders(
        {
            "deal": "Warehouse acquisition",
            "geography": "CA",
            "asset_type": "industrial",
            "loan_amount_cents": 750_000_000,
            "leverage": 0.70,
        },
        as_of="2026-07-14",
        stale_after_days=180,
        db_path=db_path,
    )

    assert "error" not in result
    assert result["matches"] == result["ranked_lenders"]
    match = result["matches"][0]
    assert match["name"] == "Legacy Regional Bank"
    assert match["fit_score"] > 0
    assert match["reasons"]
    assert "stale" in str(match["staleness_warning"]).casefold()
    assert "lender_track_record" in result["execution_history_note"]
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(fo_lenders)")
        }
    assert columns["size_max"][3] == 0
    assert columns["leverage_max"][3] == 0
    assert columns["rate_context"][3] == 0
