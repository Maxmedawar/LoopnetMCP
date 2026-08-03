"""Workspace deal-book persistence tests: saved deals, notes, and outcomes."""

import pytest

from cre_mcp.platform.repository import PlatformRepository


async def _workspace(repository: PlatformRepository) -> int:
    workspace = await repository.create_workspace("Medawar CRE")
    assert workspace is not None
    return workspace.id


async def test_save_deal_upserts_payload_and_preserves_stage(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)

    deal = await repository.save_deal(
        workspace_id,
        "crexi:deal-12",
        "Twelve-Year Absolute NNN",
        payload={"price_usd": 2_500_000},
    )

    assert deal is not None
    assert deal.stage == "watching"
    assert deal.payload["price_usd"] == 2_500_000

    moved = await repository.update_saved_deal(workspace_id, deal.id, stage="pursuing")
    assert moved is not None
    assert moved.stage == "pursuing"

    refreshed = await repository.save_deal(
        workspace_id,
        "crexi:deal-12",
        "Twelve-Year Absolute NNN",
        payload={"price_usd": 2_400_000},
    )

    assert refreshed is not None
    assert refreshed.id == deal.id
    assert refreshed.payload["price_usd"] == 2_400_000
    assert refreshed.stage == "pursuing"


async def test_saved_deal_listing_filters_by_stage(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)
    watching = await repository.save_deal(workspace_id, "crexi:a", "Deal A")
    pursued = await repository.save_deal(workspace_id, "crexi:b", "Deal B")
    assert watching is not None and pursued is not None
    assert await repository.update_saved_deal(workspace_id, pursued.id, stage="pursuing") is not None

    everything = await repository.list_saved_deals(workspace_id)
    pursuing = await repository.list_saved_deals(workspace_id, stage="pursuing")

    assert {item.deal_ref for item in everything} == {"crexi:a", "crexi:b"}
    assert [item.deal_ref for item in pursuing] == ["crexi:b"]
    assert await repository.get_saved_deal(workspace_id, watching.id) is not None


async def test_saved_deal_rejects_bad_stage_and_unknown_workspace(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)
    deal = await repository.save_deal(workspace_id, "crexi:a", "Deal A")
    assert deal is not None

    with pytest.raises(ValueError, match="stage must be one of"):
        await repository.update_saved_deal(workspace_id, deal.id, stage="daydreaming")
    with pytest.raises(ValueError, match="deal_ref"):
        await repository.save_deal(workspace_id, "   ", "Blank ref")
    assert await repository.save_deal(999, "crexi:x", "Orphan") is None


async def test_note_create_update_and_list(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)
    author = await repository.create_user("max@efreedom.com", "Max")
    deal = await repository.save_deal(workspace_id, "crexi:a", "Deal A")
    assert author is not None and deal is not None

    first = await repository.add_note(workspace_id, deal.id, author.id, "Broker says seller is motivated.")
    second = await repository.add_note(workspace_id, deal.id, author.id, "LOI draft started.")

    assert first is not None and second is not None
    edited = await repository.update_note(workspace_id, first.id, "Broker CONFIRMED seller is motivated.")
    assert edited is not None
    assert edited.body == "Broker CONFIRMED seller is motivated."

    listed = await repository.list_notes(workspace_id, deal.id)
    assert [item.id for item in listed] == [first.id, second.id]
    assert await repository.get_note(workspace_id, first.id) is not None
    assert await repository.add_note(workspace_id, 999, author.id, "Orphan") is None
    with pytest.raises(ValueError, match="body"):
        await repository.add_note(workspace_id, deal.id, author.id, "   ")


async def test_outcome_upsert_read_and_list(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)
    deal = await repository.save_deal(workspace_id, "crexi:a", "Deal A")
    assert deal is not None

    outcome = await repository.record_outcome(workspace_id,
        deal.id, closed=True, purchase_price=2_450_000
    )

    assert outcome is not None
    assert outcome.closed is True
    assert outcome.purchase_price == 2_450_000

    revised = await repository.record_outcome(workspace_id,
        deal.id, closed=True, purchase_price=2_400_000, notes="Re-traded at diligence."
    )

    assert revised is not None
    assert revised.purchase_price == 2_400_000
    fetched = await repository.get_outcome(workspace_id, deal.id)
    assert fetched is not None
    assert fetched.notes == "Re-traded at diligence."
    assert [item.saved_deal_id for item in await repository.list_outcomes(workspace_id)] == [deal.id]


async def test_outcome_validation_and_unknown_deal(tmp_path):
    repository = PlatformRepository(tmp_path / "platform.db")
    workspace_id = await _workspace(repository)
    deal = await repository.save_deal(workspace_id, "crexi:a", "Deal A")
    assert deal is not None

    with pytest.raises(ValueError, match="purchase_price"):
        await repository.record_outcome(workspace_id, deal.id, closed=True)
    with pytest.raises(ValueError, match="purchase_price"):
        await repository.record_outcome(workspace_id, deal.id, closed=True, purchase_price=-5)
    assert await repository.record_outcome(workspace_id, 999, closed=False) is None
