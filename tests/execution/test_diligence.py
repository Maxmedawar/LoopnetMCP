"""Asset-aware diligence plan and clock tests."""

from datetime import date, timedelta

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.execution.diligence import due_diligence_plan
from tests.scoring.builders import deal_context


@pytest.mark.asyncio
async def test_retail_nnn_gets_estoppel_snda_and_core_items(tmp_path):
    ctx = deal_context(property_type="retail", raw={"strategy": "nnn_retail"})
    plan = await due_diligence_plan(
        ctx,
        dd_days=30,
        start_date="2026-07-13",
        store=DealStore(tmp_path / "deals.db"),
    )
    by_key = {item.key: item for item in plan.items}

    assert {"tenant_estoppel", "snda", "co_tenancy_go_dark", "phase_i"} <= set(by_key)
    assert "estoppel" in by_key["tenant_estoppel"].label.casefold()
    assert "SNDA" in by_key["snda"].label
    assert by_key["snda"].what_should_make_you_terminate
    assert plan.persistence_status == "saved"
    assert plan.asset_class == "retail/NNN"


@pytest.mark.asyncio
async def test_multifamily_gets_unit_walk_utilities_payroll_and_deferred_scope(tmp_path):
    plan = await due_diligence_plan(
        deal_context(property_type="multifamily", units=24),
        store=DealStore(tmp_path / "deals.db"),
    )
    keys = {item.key for item in plan.items}

    assert {"unit_walks", "utilities", "payroll_staffing", "deferred_maintenance"} <= keys
    assert "tenant_estoppel" not in keys
    assert "snda" not in keys
    assert plan.asset_class == "multifamily"


@pytest.mark.asyncio
async def test_deadlines_are_back_solved_from_dd_period_and_ordered(tmp_path):
    start = date(2026, 7, 13)
    plan = await due_diligence_plan(
        deal_context(property_type="office"),
        dd_days=18,
        start_date=start,
        store=DealStore(tmp_path / "deals.db"),
    )

    assert plan.expiration_date == start + timedelta(days=18)
    assert [item.due_offset_days for item in plan.items] == sorted(
        item.due_offset_days for item in plan.items
    )
    assert all(item.deadline == start + timedelta(days=item.due_offset_days) for item in plan.items)
    assert all(item.deadline <= plan.expiration_date for item in plan.items)
    assert plan.items[-1].deadline < plan.expiration_date


@pytest.mark.asyncio
async def test_regenerated_plan_preserves_persisted_status(tmp_path):
    store = DealStore(tmp_path / "deals.db")
    ctx = deal_context(property_type="retail")
    first = await due_diligence_plan(ctx, store=store)
    assert await store.set_dd_item_status(first.deal_id, "phase_i", "in_progress")

    regenerated = await due_diligence_plan(ctx, store=DealStore(store.db_path))
    phase_i = next(item for item in regenerated.items if item.key == "phase_i")

    assert phase_i.status == "in_progress"
    assert "calendar days remain" in regenerated.countdown_summary


@pytest.mark.asyncio
async def test_bad_clock_inputs_are_rejected(tmp_path):
    ctx = deal_context()
    with pytest.raises(ValueError, match="positive integer"):
        await due_diligence_plan(ctx, dd_days=0, store=DealStore(tmp_path / "deals.db"))
    with pytest.raises(ValueError, match="ISO date"):
        await due_diligence_plan(
            ctx,
            start_date="07/13/2026",
            store=DealStore(tmp_path / "deals.db"),
        )
