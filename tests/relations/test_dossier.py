"""Cross-ledger dossier aggregation and evidence-honesty tests."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.fund.engagement import record_investor_touch
from cre_mcp.ledger.models import ClaimOutcomeRecord, DefectRecord, QuoteRecord
from cre_mcp.ledger.store import LedgerStore
from cre_mcp.negotiation.commitments import CommitmentStore
from cre_mcp.relations.dossier import counterparty_dossier


COUNTERPARTY = "Acme Capital Partners"


def _source_counts(path) -> dict[str, int]:
    tables = (
        "claim_ledger",
        "quote_ledger",
        "defect_ledger",
        "neg_commitments",
        "deal_events",
        "ir_touches",
    )
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


@pytest.mark.asyncio
async def test_dossier_aggregates_every_permissioned_source_with_sample_sizes(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "relations.db"
    ledger = LedgerStore(path)
    deals = DealStore(path)
    commitments = CommitmentStore(path)
    deal_id = await deals.save_deal(
        listing_factory(
            "acme-1",
            broker_name=COUNTERPARTY,
            broker_company=COUNTERPARTY,
        )
    )
    assert deal_id == "crexi:acme-1"

    await ledger.record_claims(
        [
            ClaimOutcomeRecord(
                deal_id=deal_id,
                field="noi",
                counterparty=COUNTERPARTY,
                counterparty_role="broker",
                claimed_value=520_000,
                claimed_doc_kind="om",
                proven_value=500_000,
                proven_doc_kind="t12",
                verdict="corroborated",
                source_document_id="om-1",
                recorded_at="2026-07-01T12:00:00+00:00",
            ),
            ClaimOutcomeRecord(
                deal_id=deal_id,
                field="rentable_sf",
                counterparty=COUNTERPARTY,
                counterparty_role="broker",
                claimed_value=20_000,
                claimed_doc_kind="om",
                proven_value=20_000,
                proven_doc_kind="survey",
                verdict="corroborated",
                source_document_id="om-2",
                recorded_at="2026-07-02T12:00:00+00:00",
            ),
            ClaimOutcomeRecord(
                deal_id=deal_id,
                field="base_rent",
                counterparty=COUNTERPARTY,
                counterparty_role="broker",
                claimed_value=30.0,
                claimed_doc_kind="om",
                proven_value=25.0,
                proven_doc_kind="lease",
                verdict="overridden",
                delta_pct=0.20,
                severity="material",
                source_document_id="om-3",
                recorded_at="2026-07-03T12:00:00+00:00",
            ),
        ]
    )
    quote = QuoteRecord(
        quote_id="qt_acme",
        deal_id=deal_id,
        lender=COUNTERPARTY,
        rate_pct=6.25,
        proceeds=8_000_000,
        quoted_at="2026-07-04T12:00:00+00:00",
    )
    await ledger.record_quote(quote)
    await ledger.resolve_quote(
        quote.quote_id,
        stage="closed",
        final_rate_pct=6.50,
        final_proceeds=7_600_000,
    )
    await ledger.record_defect(
        DefectRecord(
            defect_id="df_acme",
            deal_id=deal_id,
            defect_type="lease_expiry_cliff",
            description=f"Attributed to materials supplied by {COUNTERPARTY}",
            severity="material",
            discovered_stage="diligence",
            discovered_by=COUNTERPARTY,
            outcome="open",
            flagged_at="2026-07-05T12:00:00+00:00",
        )
    )

    kept = commitments.record_commitment_note(
        deal_id,
        "Deliver tenant financials",
        "them",
        due="2026-07-05",
        made_at="2026-07-01T09:00:00+00:00",
    )
    broken = commitments.record_commitment_note(
        deal_id,
        "Deliver estoppels",
        "them",
        due="2026-07-06",
        made_at="2026-07-02T09:00:00+00:00",
    )
    commitments.record_commitment_note(
        deal_id,
        "Return title comments",
        "us",
        due="2026-07-20",
        made_at="2026-07-03T09:00:00+00:00",
    )
    commitments.update_commitment_status(kept["id"], "kept")
    commitments.update_commitment_status(broken["id"], "broken")

    await deals.log_deal_event(
        deal_id,
        "counterparty_call",
        {"counterparty": COUNTERPARTY, "role": "seller", "summary": "Pricing call"},
        "2026-07-06T18:00:00+00:00",
    )
    await deals.log_deal_event(
        deal_id,
        "document_received",
        {"from": COUNTERPARTY, "summary": "Received partial estoppel package"},
        "2026-07-07T18:00:00+00:00",
    )
    record_investor_touch(
        COUNTERPARTY,
        "meeting",
        at="2026-07-08T18:00:00+00:00",
        db_path=path,
    )
    record_investor_touch(
        COUNTERPARTY,
        "email",
        at="2026-07-08T19:00:00+00:00",
        db_path=path,
    )
    before = _source_counts(path)

    dossier = await counterparty_dossier(
        COUNTERPARTY,
        db_path=path,
        ledger_store=ledger,
        deal_store=deals,
        license_screen={
            "query": COUNTERPARTY,
            "sources": {
                "tx_trec_real_estate": {
                    "candidates": [{"license": "TX-100", "status": "inactive"}]
                }
            },
            "disciplinary_summary": {
                "flags": [{"kind": "inactive_license_candidate"}]
            },
        },
    )

    assert dossier["who"] == COUNTERPARTY
    assert {"broker", "lender", "investor"} <= {
        role.casefold() for role in dossier["roles_seen"]
    }
    evidence = dossier["evidence_summary"]
    expected_samples = {
        "claim_track_record": 3,
        "lender_quote_history": 1,
        "commitments": 3,
        "deal_events": 2,
        "license_screen": 1,
        "defects": 1,
        "ir_touches": 2,
    }
    for source, expected in expected_samples.items():
        assert evidence[source]["sample_size"] == expected, source
    assert evidence["claim_track_record"]["claims_corroborated"] == 2
    assert evidence["claim_track_record"]["claims_overridden"] == 1
    assert evidence["lender_quote_history"]["closed"] == 1
    assert evidence["commitments"]["broken_by_them"] == 1
    assert dossier["last_interaction"] is not None
    rendered = str(dossier).casefold()
    assert "anecdote" in rendered
    assert "overridden" in rendered
    assert "broken" in rendered
    assert "inactive" in rendered
    assert "lease_expiry_cliff" in rendered
    assert _source_counts(path) == before, "dossier reads must not mutate source ledgers"


@pytest.mark.asyncio
async def test_dossier_empty_history_is_honest_and_nullable(tmp_path) -> None:
    dossier = await counterparty_dossier(
        "Never Recorded LLC",
        db_path=tmp_path / "empty.db",
        license_screen=None,
    )

    assert dossier["who"] == "Never Recorded LLC"
    assert dossier["roles_seen"] == []
    assert dossier["last_interaction"] is None
    assert all(
        section["sample_size"] == 0
        for section in dossier["evidence_summary"].values()
    )
    assert "anecdote, not signal" in str(dossier).casefold()
