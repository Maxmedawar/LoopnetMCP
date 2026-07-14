"""Unattended deal detection tests."""

from datetime import date

import pytest

from cre_mcp.command.staleness import unattended_deals
from cre_mcp.deals.store import DealStore

from .conftest import dd_item, listing


@pytest.mark.asyncio
async def test_unattended_event_window_stage_stuck_and_overdue_dd(
    command_db,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        DealStore,
        "_now",
        staticmethod(lambda: "2026-06-20T00:00:00+00:00"),
    )
    store = DealStore(command_db)
    stuck = await store.save_deal(listing("stuck-loi"))
    recent = await store.save_deal(listing("recent-loi"))
    overdue = await store.save_deal(listing("overdue"))
    assert stuck and recent and overdue
    assert await store.update_stage(stuck, "loi")
    assert await store.update_stage(recent, "loi")
    assert await store.update_stage(overdue, "diligence")
    assert await store.log_deal_event(
        recent,
        "broker_call",
        event_ts="2026-07-12T12:00:00+00:00",
    )
    assert await store.log_deal_event(
        overdue,
        "dd_kickoff",
        event_ts="2026-07-13T12:00:00+00:00",
    )
    assert await store.save_dd_items(
        overdue,
        [dd_item("title", date(2026, 7, 10))],
    )

    result = unattended_deals("2026-07-14T12:00:00+00:00", db_path=command_db)
    by_id = {item["deal_id"]: item for item in result["deals"]}

    assert stuck in by_id
    assert {flag["type"] for flag in by_id[stuck]["flags"]} == {
        "no_recent_event",
        "stage_stuck",
    }
    assert recent not in by_id
    assert {flag["type"] for flag in by_id[overdue]["flags"]} == {"overdue_dd"}
    assert "Resolve overdue DD" in by_id[overdue]["attention"]
    assert "CONVENTION" in result["conventions"]["label"]


def test_unattended_days_validation(command_db):
    with pytest.raises(ValueError, match="positive integer"):
        unattended_deals(days=0, db_path=command_db)

