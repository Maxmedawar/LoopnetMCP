"""Completeness arithmetic, phase gating, matching, and empty-state tests."""

import sqlite3

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.dataroom.index import DataRoomStore, PHASE_WEIGHTS
from cre_mcp.dataroom.taxonomy import get_taxonomy
from cre_mcp.deals.store import DealStore
from cre_mcp.models.listings import Listing
from cre_mcp.truth.models import DocKind, DocumentRecord
from cre_mcp.truth.store import TruthStore


def _listing(source_id: str = "room-1") -> Listing:
    return Listing(
        source="fixture",
        source_id=source_id,
        name="Data room fixture",
        address="100 Main St",
        city="Los Angeles",
        state="CA",
        property_type="retail",
        listing_type="for-sale",
        price_usd=3_000_000,
        url=f"https://example.test/{source_id}",
    )


@pytest.mark.asyncio
async def test_completeness_math_is_hand_computable_at_loi(dataroom_db):
    deal_store = DealStore(dataroom_db)
    deal_id = await deal_store.save_deal(_listing())
    assert deal_id is not None
    store = DataRoomStore(dataroom_db)
    store.init_data_room(deal_id, "retail_nnn")
    store.update_item(deal_id, "offering_memorandum", status="reviewed")
    store.update_item(deal_id, "t12_operating_statement", status="received")
    store.update_item(deal_id, "rent_roll", status="requested")

    result = store.completeness_index(deal_id, as_of="2026-07-14")

    # Three required LOI rows, each weight 1: (1.0 + 0.7 + 0.1) / 3.
    assert result["current_phase"] == "loi"
    assert result["possible_weighted_points"] == 3.0
    assert result["earned_weighted_points"] == 1.8
    assert result["score"] == 60.0
    assert result["formula"]["phase_weights"] == PHASE_WEIGHTS
    assert all(item["phase"] == "loi" for item in result["items"] if item["graded"])


@pytest.mark.asyncio
async def test_diligence_stage_gates_in_diligence_but_not_financing(dataroom_db):
    deal_store = DealStore(dataroom_db)
    deal_id = await deal_store.save_deal(_listing("phase-gate"))
    assert deal_id is not None
    assert await deal_store.update_stage(deal_id, "diligence")
    store = DataRoomStore(dataroom_db)
    store.init_data_room(deal_id, "retail_nnn")
    store.update_item(deal_id, "offering_memorandum", status="reviewed")

    result = store.completeness_index(deal_id, as_of="2026-07-14")
    taxonomy = get_taxonomy("retail_nnn")
    loi_required = sum(item["required"] and item["phase"] == "loi" for item in taxonomy)
    diligence_required = sum(
        item["required"] and item["phase"] == "diligence" for item in taxonomy
    )
    hand_denominator = loi_required * 1.0 + diligence_required * 3.0

    assert result["current_phase"] == "diligence"
    assert result["possible_weighted_points"] == hand_denominator
    assert result["earned_weighted_points"] == 1.0
    assert result["score"] == round(100 / hand_denominator, 2)
    assert not any(
        item["graded"] for item in result["items"] if item["phase"] in {"financing", "closing"}
    )
    assert result["blockers"]
    assert {blocker["phase"] for blocker in result["blockers"]} == {"diligence"}


def test_conditional_rows_are_ungraded_until_triggered(dataroom_db):
    store = DataRoomStore(dataroom_db)
    store.init_data_room("fixture:conditional", "retail_nnn")
    before = store.completeness_index("fixture:conditional", as_of="2026-07-14")
    phase_ii_before = next(item for item in before["items"] if item["doc_key"] == "phase_ii")

    store.update_item("fixture:conditional", "phase_ii", status="requested")
    after = store.completeness_index("fixture:conditional", as_of="2026-07-14")
    phase_ii_after = next(item for item in after["items"] if item["doc_key"] == "phase_ii")

    assert phase_ii_before["conditional_active"] is False
    assert phase_ii_before["graded"] is False
    # No DealStore row means current phase remains LOI; the trigger is active but future-phase gated.
    assert phase_ii_after["conditional_active"] is True
    assert phase_ii_after["graded"] is False


@pytest.mark.asyncio
async def test_truthstore_kind_auto_match_marks_received_with_lineage(dataroom_db):
    store = DataRoomStore(dataroom_db)
    store.init_data_room("fixture:auto-match", "retail_nnn")
    truth = TruthStore(CreConfig(cache_db_path=dataroom_db))
    record = DocumentRecord(
        document_id="a" * 64,
        deal_id="fixture:auto-match",
        doc_kind=DocKind.T12,
        source_channel="uploaded",
        origin="t12.csv",
        blob_path="",
        parse_status="parsed",
        ingested_at="2026-07-14T08:00:00+00:00",
    )
    saved = await truth.save_document(record, b"line,amount\nnoi,1\n", [], ext="csv")
    assert saved is not None

    result = store.completeness_index("fixture:auto-match", as_of="2026-07-14")
    t12 = next(item for item in result["items"] if item["doc_key"] == "t12_operating_statement")

    assert t12["status"] == "received"
    assert t12["source_document_id"] == "a" * 64
    assert result["auto_matches"][0]["match_basis"] == "TruthStore doc_kind convention"
    assert "does not prove a complete set" in result["auto_match_limit"]


def test_updates_surface_unassigned_gaps_and_preserve_assignment(dataroom_db):
    store = DataRoomStore(dataroom_db)
    store.init_data_room("fixture:assigned", "retail_nnn")
    updated = store.update_item(
        "fixture:assigned",
        "rent_roll",
        status="requested",
        assignee="Alex",
        due_date="2026-07-20",
    )
    result = store.completeness_index("fixture:assigned", as_of="2026-07-14")

    assert updated["assignee"] == "Alex"
    assert updated["due_date"] == "2026-07-20"
    assert all(gap["doc_key"] != "rent_roll" for gap in result["unassigned_gaps"])
    assert any(gap["assignee"] is None for gap in result["unassigned_gaps"])


def test_empty_deal_is_honest_and_store_owns_only_its_tables(dataroom_db):
    store = DataRoomStore(dataroom_db)
    result = store.completeness_index("fixture:empty", as_of="2026-07-14")
    with sqlite3.connect(dataroom_db) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert result["initialized"] is False
    assert result["score"] is None
    assert result["items"] == []
    assert result["blockers"] == []
    assert {"dataroom_items", "completeness_index"} <= names
    assert "deals" not in names
    assert "truth_documents" not in names
