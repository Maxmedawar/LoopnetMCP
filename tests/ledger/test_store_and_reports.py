"""Ledger persistence, idempotency, retrade math, and honest reporting."""

from datetime import UTC, datetime

import pytest

from cre_mcp.ledger.models import ClaimOutcomeRecord, DefectRecord, QuoteRecord
from cre_mcp.ledger.report import (
    counterparty_track_record,
    defect_outcome_stats,
    lender_track_record,
)
from cre_mcp.ledger.store import LedgerStore, new_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _claim(deal="crexi:1", field="noi", verdict="overridden", delta=0.19,
           counterparty="Big Broker Co", doc_id="om-doc") -> ClaimOutcomeRecord:
    return ClaimOutcomeRecord(
        deal_id=deal, field=field, counterparty=counterparty,
        counterparty_role="broker", claimed_value=500_000.0,
        claimed_doc_kind="offering_memorandum", proven_value=420_000.0,
        proven_doc_kind="lease", verdict=verdict, delta_pct=delta,
        source_document_id=doc_id, recorded_at=_now(),
    )


@pytest.mark.asyncio
async def test_claim_writes_are_idempotent(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    first = await store.record_claims([_claim()])
    second = await store.record_claims([_claim()])  # same identity -> skipped
    assert (first, second) == (1, 0)
    assert len(await store.claims_for(counterparty="Big Broker Co")) == 1


@pytest.mark.asyncio
async def test_claims_persist_across_instances_and_decode_numbers(tmp_path):
    path = tmp_path / "ledger.db"
    await LedgerStore(path).record_claims([_claim()])
    rows = await LedgerStore(path).claims_for(deal_id="crexi:1")
    assert rows[0].claimed_value == 500_000.0  # decoded back to float
    assert rows[0].verdict == "overridden"


@pytest.mark.asyncio
async def test_quote_resolution_computes_retrade(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    quote = QuoteRecord(
        quote_id=new_id("qt"), deal_id="crexi:1", lender="First Bank",
        rate_pct=6.50, proceeds=10_000_000, quoted_at=_now(),
    )
    await store.record_quote(quote)
    resolved = await store.resolve_quote(
        quote.quote_id, stage="closed", final_rate_pct=6.85, final_proceeds=9_200_000,
    )
    assert resolved.retrade_rate_bps == pytest.approx(35.0)
    assert resolved.retrade_proceeds_pct == pytest.approx(-0.08)
    assert resolved.stage == "closed"
    assert resolved.days_quote_to_close == 0


@pytest.mark.asyncio
async def test_resolve_unknown_quote_returns_none(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    assert await store.resolve_quote("qt_missing", stage="died") is None


@pytest.mark.asyncio
async def test_defect_lifecycle(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    defect = DefectRecord(
        defect_id=new_id("df"), deal_id="crexi:1", defect_type="noi_overstated",
        description="OM NOI 19% above lease-verified", severity="material",
        discovered_stage="diligence", discovered_by="deal_truth_report",
        flagged_at=_now(),
    )
    await store.record_defect(defect)
    resolved = await store.resolve_defect(
        defect.defect_id, outcome="retrade", outcome_notes="price cut", dollar_impact=-250_000,
    )
    assert resolved.outcome == "retrade"
    assert resolved.dollar_impact == -250_000
    assert resolved.resolved_at is not None


@pytest.mark.asyncio
async def test_counterparty_track_record_math_and_small_sample_honesty(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    await store.record_claims(
        [
            _claim(doc_id="om-1", field="noi", verdict="overridden", delta=0.20),
            _claim(doc_id="om-2", field="noi", verdict="overridden", delta=0.10),
            _claim(doc_id="om-3", field="rentable_sf", verdict="corroborated", delta=None),
        ]
    )
    record = await counterparty_track_record("Big Broker Co", store=store)
    assert record.claims_total == 3
    assert record.accuracy_rate == pytest.approx(1 / 3, abs=1e-4)
    assert record.mean_overstatement_pct == pytest.approx(0.15)
    assert record.worst_fields[0]["field"] == "noi"
    assert record.sample_warning is not None  # 3 tested claims = anecdote
    assert "anecdote" in record.sample_warning


@pytest.mark.asyncio
async def test_lender_track_record_aggregates_and_warns(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    q1 = QuoteRecord(quote_id=new_id("qt"), deal_id="d1", lender="First Bank",
                     rate_pct=6.5, proceeds=10_000_000, quoted_at=_now())
    q2 = QuoteRecord(quote_id=new_id("qt"), deal_id="d2", lender="First Bank",
                     rate_pct=7.0, proceeds=5_000_000, quoted_at=_now())
    await store.record_quote(q1)
    await store.record_quote(q2)
    await store.resolve_quote(q1.quote_id, stage="closed", final_rate_pct=6.75,
                              final_proceeds=10_000_000)
    await store.resolve_quote(q2.quote_id, stage="died")
    report = await lender_track_record("First Bank", store=store)
    assert report["closed"] == 1 and report["died"] == 1
    assert report["close_rate"] == pytest.approx(0.5)
    assert report["mean_retrade_rate_bps"] == pytest.approx(25.0)
    assert report["sample_warning"] is not None
    assert "UNCALIBRATED" in report["honesty"]


@pytest.mark.asyncio
async def test_defect_stats_by_type(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    for outcome, impact in (("retrade", -100_000.0), ("no_impact", None)):
        d = DefectRecord(
            defect_id=new_id("df"), deal_id="d1", defect_type="sf_mismatch",
            description="x", severity="warning", discovered_stage="diligence",
            discovered_by="human", flagged_at=_now(),
        )
        await store.record_defect(d)
        await store.resolve_defect(d.defect_id, outcome=outcome, dollar_impact=impact)
    stats = await defect_outcome_stats(store=store)
    row = stats["by_type"]["sf_mismatch"]
    assert row["flagged"] == 2 and row["retrade"] == 1 and row["no_impact"] == 1
    assert row["dollar_impact_total"] == -100_000.0
    assert stats["sample_warning"] is not None
