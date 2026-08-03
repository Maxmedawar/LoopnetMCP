"""Pre-call briefing composition tests."""

from __future__ import annotations

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.ledger.models import ClaimOutcomeRecord, QuoteRecord
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.negotiation.commitments import CommitmentStore
from cre_mcp.relations.briefing import meeting_briefing


@pytest.mark.asyncio
async def test_meeting_briefing_composes_open_items_last_five_and_track_record(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "briefing.db"
    counterparty = "First Regional Bank"
    deals = DealStore(path)
    ledger = LedgerStore(path)
    commitment_store = CommitmentStore(path)
    deal_id = await deals.save_deal(listing_factory("brief-1"))
    assert deal_id
    await deals.log_deal_event(
        deal_id,
        "lender_intro",
        {"counterparty": counterparty, "role": "lender", "sequence": 0},
        "2026-07-01T12:00:00+00:00",
    )
    for sequence in range(1, 7):
        detail = {
            "counterparty": counterparty,
            "role": "lender",
            "sequence": sequence,
        }
        if sequence == 6:
            detail["negotiation_state"] = "term sheet under revision"
        await deals.log_deal_event(
            deal_id,
            f"negotiation_event_{sequence}",
            detail,
            f"2026-07-{sequence + 1:02d}T12:00:00+00:00",
        )

    commitment_store.record_commitment_note(
        deal_id,
        "Bank to confirm proceeds",
        "them",
        due="2026-07-10",
        made_at="2026-07-02T09:00:00+00:00",
    )
    commitment_store.record_commitment_note(
        deal_id,
        "We will return term-sheet comments",
        "us",
        due="2026-07-11",
        made_at="2026-07-03T09:00:00+00:00",
    )
    commitment_store.record_commitment_note(
        deal_id,
        "Bank to circulate final term sheet",
        "them",
        due="2026-07-20",
        made_at="2026-07-04T09:00:00+00:00",
    )
    await ledger.record_claims(
        [
            ClaimOutcomeRecord(
                deal_id=deal_id,
                field="proceeds",
                counterparty=counterparty,
                counterparty_role="lender",
                claimed_value=7_500_000,
                claimed_doc_kind="email",
                proven_value=7_500_000,
                proven_doc_kind="term_sheet",
                verdict="corroborated",
                source_document_id="bank-email-1",
                recorded_at="2026-07-05T15:00:00+00:00",
            )
        ]
    )
    await ledger.record_quote(
        QuoteRecord(
            quote_id="qt_brief",
            deal_id=deal_id,
            lender=counterparty,
            rate_pct=6.4,
            proceeds=7_500_000,
            stage="term_sheet",
            quoted_at="2026-07-05T16:00:00+00:00",
        )
    )

    briefing = await meeting_briefing(
        counterparty,
        deal_id,
        db_path=path,
        ledger_store=ledger,
        deal_store=deals,
        as_of="2026-07-14T12:00:00+00:00",
    )

    assert briefing["counterparty"] == counterparty
    assert briefing["deal_id"] == deal_id
    assert briefing["open_commitments"]["sample_size"] == 3
    assert len(briefing["open_commitments"]["theirs"]) == 2
    assert len(briefing["open_commitments"]["ours"]) == 1
    assert {
        item["commitment"] for item in briefing["open_commitments"]["overdue"]
    } == {"Bank to confirm proceeds", "We will return term-sheet comments"}
    assert len(briefing["last_5_events"]) == 5
    assert {event["detail"]["sequence"] for event in briefing["last_5_events"]} == {
        2,
        3,
        4,
        5,
        6,
    }
    assert briefing["active_negotiation_state"]["status"] == "active_open_items"
    assert (
        briefing["active_negotiation_state"]["latest_event_type"]
        == "negotiation_event_6"
    )
    assert briefing["track_record_highlights"]["claim_track_record"]["sample_size"] == 1
    assert briefing["track_record_highlights"]["lender_quote_history"]["sample_size"] == 1
    agenda = str(briefing["suggested_agenda_items"]).casefold()
    assert "confirm proceeds" in agenda
    assert "term-sheet comments" in agenda
    assert "recorded" in briefing["scope"].casefold()


@pytest.mark.asyncio
async def test_meeting_briefing_unknown_deal_is_honest_empty(tmp_path) -> None:
    briefing = await meeting_briefing(
        "No History LLC",
        "missing-deal",
        db_path=tmp_path / "empty.db",
        as_of="2026-07-14T12:00:00+00:00",
    )

    assert briefing["last_5_events"] == []
    assert briefing["open_commitments"]["sample_size"] == 0
    assert len(briefing["suggested_agenda_items"]) == 1
    assert "no open commitments were recorded" in briefing["suggested_agenda_items"][0][
        "agenda_item"
    ].casefold()
    assert briefing["active_negotiation_state"]["status"] == "no_recorded_state"
    assert briefing["last_interaction"] is None
