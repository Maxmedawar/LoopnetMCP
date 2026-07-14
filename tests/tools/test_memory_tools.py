"""Phase 30 shadow-IC + deal-timeline tool tests."""

from unittest.mock import patch

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.models.listings import Listing
from cre_mcp.tools.memory_tools import (
    deal_timeline,
    ic_scorecard,
    log_deal_event,
    record_ic_decision,
)


def _listing() -> Listing:
    return Listing(
        source="crexi", source_id="mem-1", name="Test NNN",
        address="1 Main", city="Austin", state="TX", url="https://x/1",
    )


@pytest.mark.asyncio
async def test_shadow_ic_and_timeline(tmp_path):
    store = DealStore(tmp_path / "cache.db")
    deal_id = await store.save_deal(_listing())

    with patch("cre_mcp.tools.memory_tools.get_deal_store", return_value=store):
        rec = await record_ic_decision(
            deal_id, system_verdict="proceed", system_notes="verified NOI clean",
            expert_verdict="proceed", expert_notes="agree",
        )
        await log_deal_event(deal_id, "offer", {"price": 2_000_000})
        await log_deal_event(deal_id, "counter", {"price": 2_150_000})
        timeline = await deal_timeline(deal_id)

    assert rec["status"] == "recorded"
    assert rec["agreed"] is True
    assert len(timeline["events"]) == 2
    assert timeline["events"][0]["event_type"] == "offer"
    assert len(timeline["ic_decisions"]) == 1
    assert timeline["ic_decisions"][0]["agreed"] is True


@pytest.mark.asyncio
async def test_ic_decision_unknown_deal_errors(tmp_path):
    store = DealStore(tmp_path / "cache.db")
    with patch("cre_mcp.tools.memory_tools.get_deal_store", return_value=store):
        result = await record_ic_decision("crexi:ghost", system_verdict="kill")
    assert "unknown deal_id" in result["error"]


@pytest.mark.asyncio
async def test_ic_scorecard_scores_against_outcome(tmp_path):
    store = DealStore(tmp_path / "cache.db")
    deal_id = await store.save_deal(_listing(), score=80, grade="B", strategy="nnn_retail")

    with patch("cre_mcp.tools.memory_tools.get_deal_store", return_value=store):
        await record_ic_decision(deal_id, system_verdict="proceed", expert_verdict="kill")
        # realized: it closed and did NOT go bad -> "proceed" was correct
        await store.record_outcome(deal_id, {"closed": True, "purchase_price": 2_000_000, "went_bad": False})
        card = await ic_scorecard()

    assert card["total_ic_decisions"] == 1
    assert card["with_expert"] == 1
    assert card["system_expert_agreement_rate"] == 0.0  # system said proceed, expert said kill
    assert card["with_realized_outcome"] == 1
    assert card["system_accuracy_vs_outcome"] == 1.0  # proceed + good outcome = correct
    assert "caveat" in card
