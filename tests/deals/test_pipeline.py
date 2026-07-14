"""Persistent pipeline stages, notes, dedupe, and migration tests."""

import sqlite3

import pytest

from cre_mcp.deals.store import DealStore, PIPELINE_STAGES
from tests.scoring.builders import deal_context


def _listing(source_id: str = "pipeline-1"):
    return deal_context(source_id=source_id).listing


@pytest.mark.asyncio
async def test_pipeline_dedupes_updates_and_persists_across_instances(tmp_path):
    path = tmp_path / "pipeline.db"
    first = DealStore(path)
    deal_id = await first.save_deal(
        _listing(),
        score=82.5,
        grade="B",
        strategy="nnn_retail",
    )
    assert deal_id == "fixture:pipeline-1"
    assert await first.update_stage(deal_id, "contacted", "Broker returned my call")

    # Refreshing the same source:id updates the listing/score without resetting CRM state.
    assert await first.save_deal(_listing(), score=84.0) == deal_id
    reopened = DealStore(path)
    rows = await reopened.list_pipeline()

    assert len(rows) == 1
    assert rows[0]["stage"] == "contacted"
    assert rows[0]["score"] == 84.0
    assert rows[0]["grade"] == "B"
    assert rows[0]["strategy"] == "nnn_retail"
    assert rows[0]["last_note"]["text"] == "Broker returned my call"
    assert rows[0]["notes"][0]["stage"] == "contacted"


@pytest.mark.asyncio
async def test_pipeline_filters_stage_and_appends_notes(tmp_path):
    store = DealStore(tmp_path / "pipeline.db")
    lead = await store.save_deal(_listing("lead"))
    loi = await store.save_deal(_listing("loi"))
    assert lead and loi
    assert await store.update_stage(loi, "loi", "LOI sent")
    assert await store.update_stage(loi, "under_contract", "PSA executed")

    filtered = await store.list_pipeline("under_contract")
    stored = await store.get_deal(loi)

    assert [row["deal_id"] for row in filtered] == [loi]
    assert stored is not None
    assert [note["text"] for note in stored["notes"]] == ["LOI sent", "PSA executed"]
    assert {row["deal_id"] for row in await store.list_pipeline()} == {lead, loi}


@pytest.mark.asyncio
async def test_pipeline_rejects_unknown_stage_and_unknown_deal(tmp_path):
    store = DealStore(tmp_path / "pipeline.db")
    with pytest.raises(ValueError, match="stage must be one of"):
        await store.list_pipeline("won")
    with pytest.raises(ValueError, match="stage must be one of"):
        await store.update_stage("fixture:missing", "won")
    assert await store.update_stage("fixture:missing", "lead") is False
    assert tuple(PIPELINE_STAGES) == (
        "lead",
        "analyzing",
        "contacted",
        "loi",
        "under_contract",
        "diligence",
        "closing",
        "owned",
        "passed",
    )


@pytest.mark.asyncio
async def test_phase12_database_migrates_without_losing_deals(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE deals (
                deal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                listing_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        listing = _listing("legacy")
        connection.execute(
            "INSERT INTO deals VALUES (?, ?, ?, ?, ?, ?)",
            (
                "fixture:legacy",
                "fixture",
                "legacy",
                listing.model_dump_json(),
                "2026-07-13T00:00:00+00:00",
                "2026-07-13T00:00:00+00:00",
            ),
        )

    rows = await DealStore(path).list_pipeline()
    assert len(rows) == 1
    assert rows[0]["deal_id"] == "fixture:legacy"
    assert rows[0]["stage"] == "lead"
    assert rows[0]["notes"] == []
