"""Stalled-thread, sourcing-funnel, and mandate-routing tests."""

from __future__ import annotations

import sqlite3

import pytest

from cre_mcp.deals.store import DealStore
from cre_mcp.relations.coverage import coverage_report, route_lead
from cre_mcp.relations.stalls import record_thread_state, stalled_threads


@pytest.mark.asyncio
async def test_stalled_threads_threshold_owing_semantics_and_deal_impact_sort(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "stalls.db"
    deals = DealStore(path)
    closing_id = await deals.save_deal(listing_factory("closing"))
    lead_id = await deals.save_deal(listing_factory("lead"))
    recent_id = await deals.save_deal(listing_factory("recent"))
    assert closing_id and lead_id and recent_id
    assert await deals.update_stage(closing_id, "closing")

    record_thread_state(
        closing_id,
        "First Bank",
        "outbound",
        "final loan documents",
        "2026-07-10T12:00:00+00:00",
        "them",
        db_path=path,
    )
    record_thread_state(
        lead_id,
        "Listing Broker",
        "inbound",
        "tour availability",
        "2026-06-24T12:00:00+00:00",
        "us",
        db_path=path,
    )
    record_thread_state(
        recent_id,
        "Deal Counsel",
        "inbound",
        "title comments",
        "2026-07-10T13:00:00+00:00",
        "us",
        db_path=path,
    )

    result = stalled_threads(
        4,
        as_of="2026-07-14T12:00:00+00:00",
        db_path=path,
    )

    assert result["count"] == 2
    assert [row["deal_id"] for row in result["stalled_threads"]] == [
        closing_id,
        lead_id,
    ]
    closing, lead = result["stalled_threads"]
    assert closing["stalled_for_days"] == 4
    assert closing["who_owes_whom"] == "First Bank owes us an answer"
    assert closing["deal_stage"] == "closing"
    assert closing["deal_impact"] == "critical"
    assert lead["stalled_for_days"] == 20
    assert lead["who_owes_whom"] == "We owe Listing Broker an answer"
    assert "manual/tool-fed" in result["honesty"]
    assert "email integration is later" in result["honesty"]


def test_record_thread_state_upserts_latest_state_and_validates_awaiting(tmp_path) -> None:
    path = tmp_path / "upsert.db"
    first = record_thread_state(
        "deal-1",
        "Seller",
        "outbound",
        "estoppels",
        "2026-07-01T12:00:00+00:00",
        "them",
        "Initial request",
        db_path=path,
    )
    second = record_thread_state(
        "deal-1",
        "Seller",
        "inbound",
        "estoppels",
        "2026-07-12T12:00:00+00:00",
        "us",
        None,
        db_path=path,
    )

    assert first["who_owes_whom"] == "Seller owes us an answer"
    assert second["who_owes_whom"] == "We owe Seller an answer"
    report = stalled_threads(
        1,
        as_of="2026-07-14T12:00:00+00:00",
        db_path=path,
    )
    assert report["count"] == 1
    assert report["stalled_threads"][0]["direction"] == "inbound"
    assert report["stalled_threads"][0]["note"] is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM rel_threads").fetchone()[0] == 1

    with pytest.raises(ValueError, match="awaiting"):
        record_thread_state(
            "deal-1",
            "Seller",
            "inbound",
            "access",
            "2026-07-01T12:00:00+00:00",
            "nobody",
            db_path=path,
        )
    with pytest.raises(ValueError, match="days"):
        stalled_threads(-1, db_path=path)


@pytest.mark.asyncio
async def test_coverage_funnel_math_combines_events_and_saved_search_matches_read_only(
    tmp_path, listing_factory
) -> None:
    path = tmp_path / "coverage.db"
    deals = DealStore(path)
    deal_id = await deals.save_deal(listing_factory("coverage"))
    assert deal_id
    search_id = await deals.save_search("Texas retail", {"state": "TX"})
    assert search_id == 1
    assert await deals.record_seen(search_id, ["a", "b", "c", "c"]) == 3
    for event_type in (
        "searched",
        "listing_found",
        "screened",
        "reviewed",
        "underwritten",
        "analyzed",
        "rejected",
        "deal_passed",
        "advanced",
        "unrelated_note",
    ):
        event_id = await deals.log_deal_event(
            deal_id,
            event_type,
            {"coverage_test": True},
            "2026-07-10T12:00:00+00:00",
        )
        assert event_id is not None
    before_searches = await deals.list_searches()
    before_seen = await deals.seen_keys(search_id)

    result = coverage_report(
        {"start": "2000-01-01", "end": "2100-01-01"},
        as_of="2026-07-14T12:00:00+00:00",
        db_path=path,
    )

    assert result["counts"] == {
        "searched": 5,
        "screened": 4,
        "rejected": 2,
        "advanced": 1,
        "untouched": 1,
    }
    assert result["funnel"] == {
        "searched": 5,
        "screened": 4,
        "rejected": 2,
        "advanced": 1,
        "untouched": 1,
        "screened_from_searched_pct": 80.0,
        "rejected_from_screened_pct": 50.0,
        "advanced_from_screened_pct": 25.0,
    }
    assert result["saved_searches"] == {
        "configured_count": 1,
        "matches_first_seen_in_period": 3,
    }
    assert result["event_evidence"] == {
        "counts_by_stage": {
            "searched": 2,
            "screened": 4,
            "rejected": 2,
            "advanced": 1,
        },
        "classified_sample_size": 9,
        "unclassified_sample_size": 1,
    }
    assert result["instrumentation_gaps"] == []
    assert "instrumentation queue" in result["untouched_inventory_note"]
    assert await deals.list_searches() == before_searches
    assert await deals.seen_keys(search_id) == before_seen


def test_coverage_empty_and_invalid_period_boundaries(tmp_path) -> None:
    result = coverage_report(
        "daily",
        as_of="2026-07-14T12:00:00+00:00",
        db_path=tmp_path / "missing.db",
    )
    assert result["counts"] == {
        "searched": 0,
        "screened": 0,
        "rejected": 0,
        "advanced": 0,
        "untouched": 0,
    }
    assert result["funnel"]["screened_from_searched_pct"] is None
    with pytest.raises(ValueError, match="period"):
        coverage_report(0, db_path=tmp_path / "missing.db")
    with pytest.raises(ValueError, match="precede"):
        coverage_report(
            {"start": "2026-07-15", "end": "2026-07-14"},
            db_path=tmp_path / "missing.db",
        )


def test_route_lead_matches_state_property_type_and_capacity_with_reasons() -> None:
    result = route_lead(
        {
            "source_id": "listing-1",
            "city": "Austin",
            "state": "TX",
            "property_type": "retail",
            "price_usd": 4_000_000,
        },
        [
            {
                "name": "Alex",
                "mandates": [
                    {
                        "property_types": ["retail"],
                        "states": ["TX"],
                        "capacity": 5_000_000,
                    }
                ],
            },
            {
                "name": "Blair",
                "mandates": [{"property_types": ["industrial"], "states": ["TX"]}],
            },
        ],
    )

    assert result["candidate_count"] == 1
    assert result["recommended"]["name"] == "Alex"
    assert result["recommended"]["rank"] == 1
    reasons = " ".join(result["recommended"]["reasons"]).casefold()
    assert "property_type matched" in reasons
    assert "geography matched" in reasons
    assert "capacity matched" in reasons
    assert "verify current capacity" in result["message"].casefold()


def test_route_lead_honest_no_match_and_boundary() -> None:
    result = route_lead(
        {"source_id": "listing-2", "property_type": "retail", "state": "TX"},
        [{"name": "Industrial Lead", "mandates": {"property_types": ["industrial"]}}],
    )
    assert result["routes"] == []
    assert result["recommended"] is None
    assert result["message"] == "no recorded mandate-matched candidates"
    assert "does not establish availability" in result["honesty"]
    with pytest.raises(ValueError, match="team"):
        route_lead({}, "Alex")  # type: ignore[arg-type]
