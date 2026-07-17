"""Durable realized-outcome capture tests."""

import pytest

from cre_mcp.deals.store import DealStore
from tests.scoring.builders import deal_context


@pytest.mark.asyncio
async def test_recorded_outcome_persists_with_frozen_prediction(tmp_path):
    path = tmp_path / "outcomes.db"
    store = DealStore(path)
    ctx = deal_context(source_id="outcome-1", price=1_000_000)
    deal_id = await store.save_deal(
        ctx.listing,
        score=88,
        grade="B",
        strategy="nnn_retail",
    )
    assert deal_id is not None
    assert await store.record_outcome(
        deal_id,
        {
            "closed": True,
            "purchase_price": 925_000,
            "realized_hold_years": 4.5,
            "realized_irr": 14.2,
            "realized_equity_multiple": 1.8,
            "went_bad": False,
            "notes": "Final partnership accounting",
        },
    ) is True

    rows = await DealStore(path).get_outcomes()

    assert len(rows) == 1
    assert rows[0]["deal_id"] == deal_id
    assert rows[0]["predicted_score"] == 88
    assert rows[0]["predicted_grade"] == "B"
    assert rows[0]["purchase_price"] == 925_000
    assert rows[0]["realized_irr"] == 14.2
    assert rows[0]["went_bad"] is False

    await store.save_deal(ctx.listing, score=40, grade="D", strategy="core")
    assert await store.record_outcome(
        deal_id,
        {
            "closed": True,
            "purchase_price": 925_000,
            "realized_irr": 13.5,
        },
    ) is True
    updated = (await store.get_outcomes())[0]
    assert updated["predicted_score"] == 88
    assert updated["predicted_grade"] == "B"
    assert updated["realized_irr"] == 13.5


@pytest.mark.asyncio
async def test_outcome_validation_and_unknown_deal_are_safe(tmp_path):
    store = DealStore(tmp_path / "outcomes.db")
    with pytest.raises(ValueError, match="purchase_price is required"):
        await store.record_outcome("missing", {"closed": True})
    with pytest.raises(ValueError, match="closed must"):
        await store.record_outcome("missing", {"closed": "yes"})
    assert await store.record_outcome(
        "missing",
        {"closed": False, "went_bad": True},
    ) is False
    assert await store.get_outcomes() == []
