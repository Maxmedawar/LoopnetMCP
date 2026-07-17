"""Evidence-fit ranking tests for the who-to-call framing."""

from __future__ import annotations

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.fund.engagement import record_investor_touch
from cre_mcp.ledger.models import ClaimOutcomeRecord, QuoteRecord
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.relations.whotocall import who_to_call


def _claim(
    name: str,
    deal_id: str,
    verdict: str,
    document_id: str,
    recorded_at: str,
) -> ClaimOutcomeRecord:
    return ClaimOutcomeRecord(
        deal_id=deal_id,
        field="noi",
        counterparty=name,
        counterparty_role="broker",
        claimed_value=500_000,
        claimed_doc_kind="om",
        proven_value=500_000 if verdict == "corroborated" else 425_000,
        proven_doc_kind="t12",
        verdict=verdict,
        delta_pct=None if verdict == "corroborated" else 0.1765,
        source_document_id=document_id,
        recorded_at=recorded_at,
    )


@pytest.mark.asyncio
async def test_who_to_call_ranks_role_track_record_recency_and_touch_strength(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "rank.db"
    ledger = LedgerStore(path)
    deals = DealStore(path)
    alpha = "Alpha Brokerage"
    beta = "Beta Brokerage"
    alpha_deal = await deals.save_deal(
        listing_factory("alpha", broker_name=alpha, broker_company=alpha)
    )
    beta_deal = await deals.save_deal(
        listing_factory("beta", broker_name=beta, broker_company=beta)
    )
    assert alpha_deal and beta_deal
    await ledger.record_claims(
        [
            _claim(alpha, alpha_deal, "corroborated", "a-1", "2026-07-10T12:00:00+00:00"),
            _claim(alpha, alpha_deal, "corroborated", "a-2", "2026-07-11T12:00:00+00:00"),
            _claim(beta, beta_deal, "overridden", "b-1", "2026-01-01T12:00:00+00:00"),
            _claim(beta, beta_deal, "overridden", "b-2", "2026-01-02T12:00:00+00:00"),
        ]
    )
    for index, at in enumerate(
        (
            "2026-06-20T12:00:00+00:00",
            "2026-07-01T12:00:00+00:00",
            "2026-07-12T12:00:00+00:00",
        )
    ):
        record_investor_touch(
            alpha,
            "meeting" if index == 2 else "email",
            at=at,
            db_path=path,
        )
    record_investor_touch(
        beta,
        "email",
        at="2026-01-03T12:00:00+00:00",
        db_path=path,
    )
    await deals.log_deal_event(
        alpha_deal,
        "broker_call",
        {"counterparty": alpha, "role": "broker", "market": "Austin"},
        "2026-07-13T12:00:00+00:00",
    )
    await deals.log_deal_event(
        beta_deal,
        "broker_call",
        {"counterparty": beta, "role": "broker", "market": "Austin"},
        "2026-01-04T12:00:00+00:00",
    )

    result = await who_to_call(
        {
            "type": "listing",
            "deal_context": {
                "market": "Austin, TX",
                "property_type": "retail",
                "purpose": "source likely sellers",
            },
        },
        db_path=path,
        ledger_store=ledger,
        deal_store=deals,
        as_of="2026-07-14T12:00:00+00:00",
    )

    assert result["status"] == "ranked_recorded_candidates"
    assert [candidate["rank"] for candidate in result["candidates"]] == list(
        range(1, len(result["candidates"]) + 1)
    )
    assert result["candidates"][0]["name"] == alpha
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]
    for candidate in result["candidates"]:
        assert candidate["reasons"]
        assert candidate["evidence"]["source_sample_sizes"]["claim_ledger"] == 2
    alpha_reasons = " ".join(result["candidates"][0]["reasons"]).casefold()
    assert "role" in alpha_reasons
    assert "track" in alpha_reasons or "corrobor" in alpha_reasons
    assert "recen" in alpha_reasons
    assert "touch" in alpha_reasons or "relationship" in alpha_reasons
    assert "never an instruction" in result["framing"].casefold()
    assert "anecdote" in str(result).casefold()


@pytest.mark.asyncio
async def test_who_to_call_honest_empty_has_no_synthetic_candidates(tmp_path) -> None:
    result = await who_to_call(
        {"type": "counsel", "deal_context": {"state": "TX"}},
        db_path=tmp_path / "empty.db",
        as_of="2026-07-14T12:00:00+00:00",
    )

    assert result["status"] == "no_recorded_candidates"
    assert result["candidates"] == []
    rendered = str(result).casefold()
    assert "no recorded candidates" in rendered
    assert "never an instruction" in rendered


@pytest.mark.asyncio
async def test_who_to_call_recency_uses_newest_evidence_across_sources(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "cross-source-recency.db"
    lender = "Newest Evidence Bank"
    deals = DealStore(path)
    ledger = LedgerStore(path)
    deal_id = await deals.save_deal(listing_factory("recency"))
    assert deal_id
    await deals.log_deal_event(
        deal_id,
        "lender_call",
        {"counterparty": lender, "role": "lender"},
        "2025-01-01T12:00:00+00:00",
    )
    await ledger.record_quote(
        QuoteRecord(
            quote_id="qt_newest",
            deal_id=deal_id,
            lender=lender,
            rate_pct=6.25,
            quoted_at="2026-07-13T12:00:00+00:00",
        )
    )

    result = await who_to_call(
        {"type": "debt", "deal_context": {}},
        db_path=path,
        ledger_store=ledger,
        deal_store=deals,
        as_of="2026-07-14T12:00:00+00:00",
    )

    assert result["candidates"][0]["last_interaction"] == "2026-07-13T12:00:00+00:00"
    assert "1 day(s)" in " ".join(result["candidates"][0]["reasons"])


@pytest.mark.asyncio
async def test_who_to_call_rejects_unknown_need_type(tmp_path) -> None:
    with pytest.raises(ValueError, match="type"):
        await who_to_call(
            {"type": "magician", "deal_context": {}},
            db_path=tmp_path / "invalid.db",
        )
