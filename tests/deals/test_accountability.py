"""Job 3: owner / next-action / due-date accountability on deals."""

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.models import Listing


def _listing(source_id: str = "acct-1") -> Listing:
    return Listing(
        source="crexi",
        source_id=source_id,
        name="Accountability Test NNN",
        address="1 Main St",
        city="Austin",
        state="TX",
        property_type="retail",
        listing_type="for-sale",
        price_usd=1_000_000,
        url=f"https://www.crexi.com/properties/{source_id}",
    )


@pytest.mark.asyncio
async def test_assign_and_flag_unaccounted(tmp_path):
    store = DealStore(tmp_path / "cache.db")
    await store.save_deal(_listing("acct-1"))
    await store.save_deal(_listing("acct-2"))

    # Both start fully unaccounted.
    flagged = await store.unaccounted_deals()
    assert {d["deal_id"] for d in flagged} == {"crexi:acct-1", "crexi:acct-2"}
    assert flagged[0]["missing"] == ["owner", "next_action", "next_action_due"]

    # Fully assigning one removes it from the flag list.
    updated = await store.assign_deal(
        "crexi:acct-1", owner="Max", next_action="send LOI",
        next_action_due="2026-07-21",
    )
    assert updated["owner"] == "Max"
    flagged = await store.unaccounted_deals()
    assert {d["deal_id"] for d in flagged} == {"crexi:acct-2"}

    # Partial assignment still flags, naming only the missing fields.
    await store.assign_deal("crexi:acct-2", owner="Cherif")
    flagged = await store.unaccounted_deals()
    assert flagged[0]["missing"] == ["next_action", "next_action_due"]


@pytest.mark.asyncio
async def test_assign_unknown_deal_returns_none_and_none_leaves_unchanged(tmp_path):
    store = DealStore(tmp_path / "cache.db")
    assert await store.assign_deal("crexi:missing", owner="X") is None

    await store.save_deal(_listing("acct-3"))
    await store.assign_deal("crexi:acct-3", owner="Max", next_action="call broker")
    # Setting only the due date must not clobber owner/next_action.
    after = await store.assign_deal("crexi:acct-3", next_action_due="2026-08-01")
    assert after["owner"] == "Max"
    assert after["next_action"] == "call broker"
    assert after["next_action_due"] == "2026-08-01"
