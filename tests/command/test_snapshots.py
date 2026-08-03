"""Listing snapshot, diff, and stale-signal tests."""

import sqlite3

from cre_mcp.command.snapshots import SnapshotStore
from cre_mcp.command.stale import stale_listing_signals


def test_snapshot_diff_emits_price_status_broker_and_dom_changes(command_db):
    store = SnapshotStore(command_db)
    first = store.record_snapshot(
        {
            "listing_key": "crexi:101",
            "deal_id": "fixture:deal",
            "price": 1_000_000,
            "status": "active",
            "dom": 29,
            "broker": "Alpha CRE",
            "captured_at": "2026-07-12T06:00:00+00:00",
        }
    )
    second = store.record_snapshot(
        {
            "listing_key": "crexi:101",
            "deal_id": "fixture:deal",
            "price": 900_000,
            "status": "under contract",
            "dom": 31,
            "broker": "Beta CRE",
            "captured_at": "2026-07-14T06:00:00+00:00",
        }
    )

    events = store.diff_snapshots("crexi:101")
    by_type = {event["event_type"]: event for event in events}

    assert first["snapshot_id"] == 1
    assert second["snapshot_id"] == 2
    assert by_type["price_change"]["direction"] == "decrease"
    assert by_type["price_change"]["pct_change"] == -10.0
    assert by_type["status_change"]["to"] == "under contract"
    assert by_type["broker_change"]["to"] == "Beta CRE"
    assert by_type["dom_milestone"]["milestone_days"] == 30


def test_snapshot_store_creates_only_its_owned_schema(command_db):
    captured = SnapshotStore(command_db).record_snapshot(
        {
            "source": "loopnet",
            "source_id": "owned-schema",
            "price": "$500,000",
            "price_usd": 500_000,
        }
    )
    with sqlite3.connect(command_db) as connection:
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(listing_snapshots)")
        ]
        deal_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deals'"
        ).fetchone()

    assert columns == [
        "snapshot_id",
        "listing_key",
        "deal_id",
        "price",
        "status",
        "dom",
        "broker",
        "raw_json",
        "captured_at",
    ]
    assert captured["price"] == 500_000
    assert deal_table is None


def test_stale_listing_signal_is_explicitly_uncalibrated(command_db):
    store = SnapshotStore(command_db)
    for captured_at, price, dom in (
        ("2026-05-01T00:00:00+00:00", 1_000_000, 130),
        ("2026-06-01T00:00:00+00:00", 950_000, 160),
        ("2026-07-01T00:00:00+00:00", 900_000, 190),
    ):
        store.record_snapshot(
            {
                "listing_key": "loopnet:stale",
                "price": price,
                "dom": dom,
                "captured_at": captured_at,
            }
        )

    result = stale_listing_signals(store.list_snapshots("loopnet:stale"))

    assert result["negotiability_signal"] == "strong"
    assert result["evidence"]["price_cut_count"] == 2
    assert result["evidence"]["latest_dom"] == 190
    assert result["convention"]["label"] == "HEURISTIC CONVENTION — UNCALIBRATED"
    assert "does not establish seller motivation" in result["note"]
