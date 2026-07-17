"""Morning queue ranking and honesty tests."""

from datetime import date

import pytest

from cre_mcp.command.queue import SCORING_FORMULA, morning_action_queue
from cre_mcp.deals.store import DealStore

from .conftest import dd_item, listing


@pytest.mark.asyncio
async def test_exchange_deadline_outranks_dd_with_hand_computed_scores(
    fixed_store: DealStore,
):
    exchange_deal = await fixed_store.save_deal(listing("exchange"))
    dd_deal = await fixed_store.save_deal(listing("dd"))
    routine_deal = await fixed_store.save_deal(listing("routine"))
    assert exchange_deal and dd_deal and routine_deal
    assert await fixed_store.update_stage(exchange_deal, "closing")
    assert await fixed_store.update_stage(dd_deal, "diligence")
    assert await fixed_store.save_dd_items(
        dd_deal,
        [dd_item("survey", date(2026, 7, 15))],
    )
    assert await fixed_store.create_exchange(
        exchange_deal,
        "2026-06-01",
        "2026-07-16",
        "2026-11-28",
    )

    result = morning_action_queue("2026-07-14", db_path=fixed_store.db_path)
    queue = result["queue"]

    assert queue[0]["deal_id"] == exchange_deal
    assert queue[0]["severity"] == "value_destroying"
    assert queue[0]["score"] == 88.0  # 4 proximity × 10 severity × 2.2 closing
    assert queue[0]["score_breakdown"] == {
        "formula": SCORING_FORMULA,
        "deadline_bucket": "0_to_2_days",
        "deadline_proximity_weight": 4.0,
        "severity_weight": 10.0,
        "deal_stage": "closing",
        "deal_stage_weight": 2.2,
        "calculation": "4 × 10 × 2.2 = 88",
    }
    dd_action = next(item for item in queue if item["action"] == "Resolve DD item: Survey")
    assert dd_action["score"] == 48.0  # 4 × 6 × 2.0
    routine = next(item for item in queue if item["deal_id"] == routine_deal)
    assert routine["deadline"] == "no deadline data"
    assert routine["days_left"] is None
    assert routine["score"] == 0.2  # 0.25 × 1 × 0.8
    assert result["scoring_formula"] == SCORING_FORMULA
    assert "CONVENTION" in result["scoring_convention"]["label"]


@pytest.mark.asyncio
async def test_pending_ic_and_missing_deadline_are_never_silently_dropped(
    fixed_store: DealStore,
):
    deal_id = await fixed_store.save_deal(listing("pending-ic"))
    assert deal_id
    assert await fixed_store.update_stage(deal_id, "loi")
    assert await fixed_store.record_ic_decision(
        deal_id,
        system_verdict="proceed_with_conditions",
    )

    result = morning_action_queue("2026-07-14", db_path=fixed_store.db_path)

    assert result["count"] == 1
    assert result["queue"][0]["deal_id"] == deal_id
    assert result["queue"][0]["deadline"] == "no deadline data"
    assert "expert verdict" in result["queue"][0]["why"]


def test_empty_database_returns_empty_queue_with_note(command_db):
    result = morning_action_queue("2026-07-14", db_path=command_db)

    assert result["queue"] == []
    assert result["count"] == 0
    assert result["note"]
    assert result["scoring_formula"] == SCORING_FORMULA

