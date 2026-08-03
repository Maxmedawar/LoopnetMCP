"""Investor and commitment persistence tests."""

import pytest

from cre_mcp.deals.store import DealStore
from tests.scoring.builders import deal_context


@pytest.mark.asyncio
async def test_investors_and_commitments_persist_across_store_instances(tmp_path):
    path = tmp_path / "capital.db"
    first = DealStore(path)
    deal_id = await first.save_deal(deal_context(source_id="raise-deal").listing)
    assert deal_id is not None
    investor_id = await first.add_investor(
        "Jordan LP",
        accredited=True,
        accreditation_verified=False,
        relationship="preexisting",
        contact={"email": "jordan@example.test"},
    )
    assert investor_id is not None
    commitment_id = await first.record_commitment(deal_id, investor_id, 250_000)
    assert commitment_id is not None

    investors = await DealStore(path).list_investors()
    assert len(investors) == 1
    assert investors[0]["contact"] == {"email": "jordan@example.test"}
    assert investors[0]["total_commitments"] == 250_000
    assert investors[0]["commitments"][0]["deal_id"] == deal_id


@pytest.mark.asyncio
async def test_commitment_upsert_preserves_id_and_updates_amount(tmp_path):
    store = DealStore(tmp_path / "capital.db")
    deal_id = await store.save_deal(deal_context(source_id="raise-deal").listing)
    investor_id = await store.add_investor("Jordan LP", relationship="preexisting")
    assert deal_id is not None and investor_id is not None

    first_id = await store.record_commitment(deal_id, investor_id, 100_000)
    second_id = await store.record_commitment(deal_id, investor_id, 175_000)
    assert first_id == second_id
    assert (await store.get_commitment(first_id))["amount"] == 175_000


@pytest.mark.asyncio
async def test_investor_and_commitment_validation(tmp_path):
    store = DealStore(tmp_path / "capital.db")
    with pytest.raises(ValueError, match="cannot be blank"):
        await store.add_investor(" ")
    with pytest.raises(ValueError, match="preexisting or new"):
        await store.add_investor("Investor", relationship="friend")
    with pytest.raises(ValueError, match="requires accredited=True"):
        await store.add_investor(
            "Investor",
            accredited=None,
            accreditation_verified=True,
        )
    with pytest.raises(ValueError, match="greater than zero"):
        await store.record_commitment("missing", 1, 0)

    assert await store.record_commitment("missing", 1, 100) is None
