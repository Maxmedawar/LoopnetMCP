"""Post-close operating calendar and persistence tests."""

from datetime import date

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.models.enrichment import ListingFacts
from cre_mcp.ops.playbook import operating_playbook
from tests.scoring.builders import deal_context


@pytest.mark.asyncio
async def test_playbook_is_asset_aware_dates_lease_facts_and_persists(tmp_path):
    store = DealStore(tmp_path / "ops.db")
    ctx = deal_context(
        source_id="ops-nnn",
        raw={
            "closing_date": "2026-08-01",
            "lease_expiration_date": "2036-07-31",
            "option_deadline": "2035-07-31",
            "next_rent_escalation_date": "2027-08-01",
        },
    )
    ctx.facts = ListingFacts(
        strategy_hint="nnn_retail",
        lease_years_remaining=10,
        rent_escalations=2,
        nnn_purity="absolute",
    )

    playbook = await operating_playbook(ctx, store=store, as_of=date(2026, 7, 13))
    month_one = " ".join(item.label for item in playbook.month_one).casefold()
    recurring = " ".join(item.label for item in playbook.recurring)
    critical = {item.key: item for item in playbook.critical_dates}

    assert len(playbook.month_one) == 5
    assert "rent collection" in month_one
    assert "w-9" in month_one and "estoppel" in month_one
    assert "book" in month_one and "insurance" in month_one
    assert "notice-of-new-owner" in month_one
    assert "REASSESSMENT" in recurring
    assert "NNN CAM" in recurring
    assert "roof/structure" in recurring
    assert critical["lease_expiration"].event_date == date(2036, 7, 31)
    assert critical["lease_option_1"].event_date == date(2035, 7, 31)
    assert critical["lease_escalation_1"].event_date == date(2027, 8, 1)
    assert critical["lease_escalation_1"].reminder_days_before
    assert "find_deals" in " ".join(item.action for item in playbook.nudges)
    assert playbook.persistence_status == "saved"

    persisted = await DealStore(tmp_path / "ops.db").get_ops_events(playbook.deal_id)
    assert {item["key"] for item in persisted} >= {
        "month1_rent_ach",
        "recurring_tax_reassessment",
        "lease_expiration",
        "lease_option_1",
        "lease_escalation_1",
        "nudge_exit_1031",
    }


@pytest.mark.asyncio
async def test_playbook_models_missing_dates_and_preserves_existing_status(tmp_path):
    store = DealStore(tmp_path / "ops.db")
    ctx = deal_context(source_id="ops-modeled")
    ctx.facts = ListingFacts(
        strategy_hint="nnn_retail",
        lease_years_remaining=5,
        rent_escalations=1.5,
    )
    first = await operating_playbook(ctx, store=store, as_of="2026-01-01")
    assert await store.set_ops_event_status(
        first.deal_id,
        "month1_rent_ach",
        "complete",
    ) is True

    second = await operating_playbook(ctx, store=store, as_of="2026-01-01")
    persisted = await store.get_ops_events(second.deal_id)
    completed = next(item for item in persisted if item["key"] == "month1_rent_ach")

    assert completed["status"] == "complete"
    assert any("modeled" in item.date_source for item in second.critical_dates)
    assert "starting control system" in second.guardrail
