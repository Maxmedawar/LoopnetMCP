"""Notice, lineage, and plain-boundary completion proofs."""

from __future__ import annotations

import inspect

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.leaseops import tools
from cre_mcp.leaseops.lineage import trace_input
from cre_mcp.leaseops.notices import COUNSEL_ROUTING, draft_obligation_notice
from cre_mcp.truth.models import (
    DocKind,
    DocumentRecord,
    ExtractedFigure,
    ExtractionMethod,
    FieldClaim,
    Lineage,
)
from cre_mcp.truth.store import TruthStore


def test_notice_quotes_clause_calculates_deadline_and_never_sends():
    quote = "Tenant shall cure a monetary default within ten (10) calendar days."
    result = draft_obligation_notice(
        {
            "cited_clause": {
                "quote": quote,
                "locator": "Lease §18.2",
                "cure_days": 10,
                "day_basis": "calendar_days",
            },
            "tenant": "Example Tenant LLC",
        },
        "cure",
        {
            "event_date": "2026-07-14",
            "default_amount_cents": 125_001,
            "breach_description": "July base rent remains unpaid.",
        },
    )

    assert quote in result["content"]
    assert result["deadline_math"]["deadline"] == "2026-07-24"
    assert result["deadline_math"]["clause_citation"]["quote"] == quote
    assert result["amounts_cents"]["default_amount_cents"] == 125_001
    assert result["counsel_routing"] == COUNSEL_ROUTING
    assert COUNSEL_ROUTING in result["content"]
    assert result["sent"] is False
    assert result["performed_actions"] == []
    assert result["delivery_status"] == "not_sent"


def test_notice_rejects_unknown_structured_input_at_tool_boundary():
    result = tools.draft_obligation_notice(
        {"cited_clause": {"quote": "Notice in 5 days.", "locator": "§1", "days": 5}},
        "default",
        {"event_date": "2026-07-14", "ammount_cents": 10},
    )

    assert "error" in result
    assert "ammount_cents" in result["error"]


def _claim(document_id: str, kind: DocKind, value: float, raw: str, page: int) -> FieldClaim:
    return FieldClaim(
        field="base_rent",
        subject="Suite 101",
        figure=ExtractedFigure(
            value=value,
            unit="usd_per_month",
            confidence=0.95,
            lineage=Lineage(
                document_id=document_id,
                doc_kind=kind,
                page=page,
                raw_text=raw,
                origin=f"{document_id}.pdf",
                extraction_method=ExtractionMethod.PDF_TEXT_REGEX,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_trace_input_walks_seeded_truth_store_winner_and_loser(tmp_path):
    db_path = tmp_path / "truth.sqlite"
    store = TruthStore(CreConfig(cache_db_path=db_path))
    lease = _claim("lease-doc", DocKind.LEASE, 1_000, "Base Rent is $1,000", 7)
    om = _claim("om-doc", DocKind.OM, 1_200, "In-place rent: $1,200", 12)
    for claim in (lease, om):
        lineage = claim.figure.lineage
        record = DocumentRecord(
            document_id=lineage.document_id,
            deal_id="deal-lineage",
            doc_kind=lineage.doc_kind,
            source_channel="uploaded",
            origin=lineage.origin,
            blob_path="",
            n_pages=20,
            parse_status="parsed",
            ingested_at="2026-07-14T00:00:00+00:00",
        )
        saved = await store.save_document(record, b"fixture", [claim], ext="pdf")
        assert saved is not None

    result = await trace_input(
        "deal-lineage", "base_rent", "Suite 101", db_path=db_path
    )

    assert result["status"] == "resolved_with_conflict"
    assert result["winner"]["document"]["document_id"] == "lease-doc"
    assert result["winner"]["location"]["page"] == 7
    assert result["winner"]["raw_text"] == "Base Rent is $1,000"
    assert result["winner"]["claim"]["value"] == 1_000
    assert result["losers"][0]["document"]["document_id"] == "om-doc"
    assert result["losers"][0]["raw_text"] == "In-place rent: $1,200"
    assert result["groups"][0]["conflict"]["resolution"] == "auto_hierarchy"
    assert [step["role"] for step in result["lineage_chain"]] == ["winner", "loser"]
    assert result["read_only"] is True


@pytest.mark.asyncio
async def test_trace_missing_is_honest_and_tool_functions_are_explicit(tmp_path):
    missing = await tools.trace_input_lineage(
        "deal-empty", "noi", db_path=tmp_path / "absent.sqlite"
    )

    assert missing["status"] == "missing"
    assert missing["winner"] is None
    assert "no value or source lineage was inferred" in missing["honest_gap"]
    for name in tools.__all__:
        function = getattr(tools, name)
        assert all(
            parameter.kind
            not in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}
            for parameter in inspect.signature(function).parameters.values()
        )
    assert "fastmcp" not in inspect.getsource(tools).casefold()


def test_certificate_tool_combines_radar_and_entered_requirement_gaps(tmp_path):
    created = tools.record_certificate(
        "tenant-tools",
        "coi",
        "Tenant LLC",
        100_000_000,
        "2026-08-01",
        "received",
        None,
        tmp_path / "tools.sqlite",
    )
    assert "error" not in created

    radar = tools.certificate_radar(
        30,
        "tenant-tools",
        [{
            "kind": "coi",
            "party": "Tenant LLC",
            "required_amount_cents": 200_000_000,
            "clause_quote": "Tenant shall carry $2,000,000 coverage.",
            "locator": "Lease §11",
        }],
        "2026-07-14",
        tmp_path / "tools.sqlite",
    )

    assert radar["expiring_count"] == 1
    assert radar["gaps_report"]["gap_count"] == 1
    assert radar["requirement_gaps"][0]["status"] == "insufficient_amount"
