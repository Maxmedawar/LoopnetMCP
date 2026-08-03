"""DealStore persistence and checklist-state tests."""

from datetime import date

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.models import DDItem, Listing


def _listing(source_id: str = "deal-12") -> Listing:
    return Listing(
        source="crexi",
        source_id=source_id,
        name="Twelve-Year Absolute NNN",
        address="100 Congress Ave",
        city="Austin",
        state="TX",
        property_type="retail",
        listing_type="for-sale",
        price_usd=2_500_000,
        url=f"https://www.crexi.com/properties/{source_id}",
    )


def _item() -> DDItem:
    return DDItem(
        key="phase_i",
        label="Phase I",
        why="Environmental liability matters.",
        what_clears_it="Clean current report.",
        what_should_make_you_terminate="Unbounded contamination.",
        who_to_hire="Environmental consultant",
        due_offset_days=10,
        deadline=date(2026, 8, 1),
    )


@pytest.mark.asyncio
async def test_save_get_and_list_persist_across_store_instances(tmp_path):
    path = tmp_path / "shared-cache.db"
    first = DealStore(path)
    deal_id = await first.save_deal(_listing())

    second = DealStore(path)
    stored = await second.get_deal("crexi:deal-12")
    deals = await second.list_deals()

    assert deal_id == "crexi:deal-12"
    assert stored is not None
    assert stored["listing"]["name"] == "Twelve-Year Absolute NNN"
    assert stored["source"] == "crexi"
    assert deals[0]["deal_id"] == deal_id
    assert deals[0]["dd_total"] == 0


@pytest.mark.asyncio
async def test_dd_status_update_persists_and_generated_upsert_preserves_it(tmp_path):
    path = tmp_path / "shared-cache.db"
    store = DealStore(path)
    deal_id = await store.save_deal(_listing())
    assert deal_id is not None
    assert await store.save_dd_items(deal_id, [_item()]) is True
    assert await store.set_dd_item_status(deal_id, "phase_i", "complete") is True

    reopened = DealStore(path)
    assert (await reopened.get_dd_items(deal_id))[0]["status"] == "complete"
    assert await reopened.save_dd_items(deal_id, [_item()]) is True
    stored = await reopened.get_deal(deal_id)

    assert stored is not None
    assert stored["dd_items"][0]["status"] == "complete"
    assert (await reopened.list_deals())[0]["dd_complete"] == 1


@pytest.mark.asyncio
async def test_plan_refresh_removes_stale_template_rows(tmp_path):
    store = DealStore(tmp_path / "shared-cache.db")
    deal_id = await store.save_deal(_listing())
    assert deal_id is not None
    stale = _item().model_copy(update={"key": "retired_template_item"})
    assert await store.save_dd_items(deal_id, [_item(), stale])

    assert await store.save_dd_items(deal_id, [_item()])
    assert [item["key"] for item in await store.get_dd_items(deal_id)] == ["phase_i"]


@pytest.mark.asyncio
async def test_unknown_item_and_invalid_status_are_rejected(tmp_path):
    store = DealStore(tmp_path / "shared-cache.db")
    deal_id = await store.save_deal(_listing())
    assert deal_id is not None

    assert await store.set_dd_item_status(deal_id, "missing", "complete") is False
    with pytest.raises(ValueError, match="status must be one of"):
        await store.set_dd_item_status(deal_id, "missing", "done")


def test_store_accepts_config_positionally(tmp_path):
    config = CreConfig(cache_db_path=tmp_path / "configured.db")
    assert DealStore(config).db_path == config.cache_db_path
