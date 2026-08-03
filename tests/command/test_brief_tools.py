"""Overnight brief composition and plain wrapper tests."""

from datetime import date
from inspect import iscoroutinefunction

import pytest

from cre_mcp.command.brief import overnight_brief
from cre_mcp.command.snapshots import SnapshotStore
from cre_mcp.command.tools import (
    flag_unattended,
    morning_queue,
    overnight_changes,
    record_listing_snapshot,
    stale_listing_signals,
)
from cre_mcp.deals.store import DealStore

from .conftest import dd_item, listing


@pytest.mark.asyncio
async def test_overnight_brief_composes_changes_deadlines_and_attention(
    command_db,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        DealStore,
        "_now",
        staticmethod(lambda: "2026-07-01T00:00:00+00:00"),
    )
    store = DealStore(command_db)
    deal_id = await store.save_deal(listing("brief"))
    assert deal_id
    assert await store.update_stage(deal_id, "loi")
    assert await store.save_dd_items(
        deal_id,
        [dd_item("environmental", date(2026, 7, 21))],
    )
    assert await store.create_exchange(
        deal_id,
        "2026-06-29",
        "2026-08-13",
        "2026-12-26",
    )
    snapshots = SnapshotStore(command_db)
    snapshots.record_snapshot(
        {
            "listing_key": "fixture:brief",
            "price": 2_000_000,
            "status": "active",
            "captured_at": "2026-07-12T06:00:00+00:00",
        }
    )
    snapshots.record_snapshot(
        {
            "listing_key": "fixture:brief",
            "price": 1_900_000,
            "status": "active",
            "captured_at": "2026-07-14T06:00:00+00:00",
        }
    )

    result = overnight_brief(
        "2026-07-14T12:00:00+00:00",
        db_path=command_db,
    )

    assert result["summary_counts"]["price_changes"] == 1
    transitions = {
        (item["source"], item["transition"])
        for item in result["approaching_deadlines"]
    }
    assert ("dd_item", "entered_7_day_window") in transitions
    assert ("exchange_clock", "entered_30_day_window") in transitions
    assert result["summary_counts"]["exchange_clock_transitions"] == 1
    assert result["needs_attention"][0]["deal_id"] == deal_id
    assert "does not yet see bids" in result["note"]


def test_plain_tools_use_configured_db_and_are_not_coroutines(command_db):
    captured = record_listing_snapshot(
        {
            "listing_key": "tool:1",
            "price": 1_000_000,
            "dom": 100,
            "captured_at": "2026-07-14T00:00:00+00:00",
        }
    )
    stale = stale_listing_signals("tool:1")

    assert captured["listing_key"] == "tool:1"
    assert stale["listing_key"] == "tool:1"
    assert stale["thin_data"] is True
    assert all(
        not iscoroutinefunction(function)
        for function in (
            morning_queue,
            overnight_changes,
            flag_unattended,
            record_listing_snapshot,
            stale_listing_signals,
        )
    )

