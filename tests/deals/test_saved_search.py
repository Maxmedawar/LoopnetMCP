"""Saved-search persistence and new-only pull alert behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from cre_mcp.access.context import TenantContext, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.deals.store import DealStore
from cre_mcp.tools.pipeline_tools import ALERT_HOSTING_NOTE, check_alerts


def _deal(source_id: str, score: float) -> dict:
    return {
        "listing": {
            "source": "crexi",
            "source_id": source_id,
            "name": f"Deal {source_id}",
            "address": "100 Congress Ave",
            "city": "Austin",
            "state": "TX",
            "url": f"https://www.crexi.com/properties/{source_id}",
        },
        "scores": [
            {"strategy": "nnn_retail", "score": score, "grade": "B"}
        ],
        "best_strategy": "nnn_retail",
    }


@pytest.mark.asyncio
async def test_saved_search_and_seen_matches_persist_across_instances(tmp_path):
    path = tmp_path / "alerts.db"
    first = DealStore(path)
    search_id = await first.save_search(
        "Austin NNN",
        {"location": "Austin, TX", "strategy": "nnn_retail", "sources": ["crexi"]},
        70,
    )
    assert search_id == 1
    assert await first.record_seen(search_id, ["crexi:one", "crexi:one"]) == 1
    assert await first.record_seen(search_id, ["crexi:one"]) == 0

    reopened = DealStore(path)
    searches = await reopened.list_searches()

    assert searches[0]["query"]["location"] == "Austin, TX"
    assert searches[0]["min_score"] == 70
    assert searches[0]["seen_count"] == 1
    assert await reopened.seen_keys(search_id) == {"crexi:one"}


@pytest.mark.asyncio
async def test_check_alerts_returns_new_only_then_none_on_recheck(tmp_path):
    store = DealStore(tmp_path / "alerts.db")
    search_id = await store.save_search(
        "Austin NNN",
        {
            "location": "Austin, TX",
            "strategy": "nnn_retail",
            "property_type": "retail",
            "price_min": 1_000_000,
            "price_max": 5_000_000,
            "size_min": None,
            "size_max": None,
            "sources": ["crexi"],
        },
        70,
    )
    assert search_id is not None
    response = {
        "deals": [
            _deal("new-a", 85),
            _deal("new-a", 85),
            _deal("new-b", 72),
            _deal("below", 60),
        ],
        "errors": {},
    }
    mocked_find = AsyncMock(return_value=response)
    with (
        patch("cre_mcp.tools.pipeline_tools.get_search_store", return_value=store),
        patch("cre_mcp.tools.pipeline_tools.find_deals", new=mocked_find),
    ):
        first = await check_alerts(search_id)
        second = await check_alerts(search_id)

    assert first["new_count"] == 2
    assert {deal["listing"]["source_id"] for deal in first["new_deals"]} == {
        "new-a",
        "new-b",
    }
    assert all(deal["saved_search_id"] == search_id for deal in first["new_deals"])
    assert second["new_count"] == 0
    assert second["new_deals"] == []
    assert (await store.list_searches())[0]["seen_count"] == 2
    assert first["hosting_note"] == ALERT_HOSTING_NOTE
    assert "cron" in first["hosting_note"]
    assert mocked_find.await_args.kwargs["min_score"] == 70
    assert mocked_find.await_args.kwargs["limit"] == 100


@pytest.mark.asyncio
async def test_check_alerts_can_check_all_searches_and_isolates_search_errors(tmp_path):
    store = DealStore(tmp_path / "alerts.db")
    first_id = await store.save_search("Austin", {"location": "Austin", "sources": ["loopnet"]})
    second_id = await store.save_search("Phoenix", {"location": "Phoenix", "sources": ["crexi"]})
    assert first_id and second_id
    mocked_find = AsyncMock(
        side_effect=[{"deals": [_deal("a", 80)], "errors": {}}, {"error": "source down"}]
    )
    with (
        patch("cre_mcp.tools.pipeline_tools.get_search_store", return_value=store),
        patch("cre_mcp.tools.pipeline_tools.find_deals", new=mocked_find),
    ):
        result = await check_alerts()

    assert result["searches_checked"] == 2
    assert result["new_count"] == 1
    assert result["errors"] == {str(second_id): "source down"}


@pytest.mark.asyncio
async def test_unknown_search_id_returns_error_dict(tmp_path):
    store = DealStore(tmp_path / "alerts.db")
    with patch("cre_mcp.tools.pipeline_tools.get_search_store", return_value=store):
        assert await check_alerts(999) == {"error": "unknown search_id: 999"}


@pytest.mark.asyncio
async def test_check_alerts_preflights_all_territories_before_claiming() -> None:
    class SearchStore:
        def __init__(self) -> None:
            self.claimed: list[tuple[int, list[str]]] = []

        async def list_searches(self):
            return [
                {
                    "id": 1,
                    "name": "Texas",
                    "query": {"location": "Austin, TX", "sources": ["loopnet"]},
                    "min_score": None,
                },
                {
                    "id": 2,
                    "name": "Stale Florida",
                    "query": {"location": "Miami, FL", "sources": ["loopnet"]},
                    "min_score": None,
                },
            ]

        async def claim_unseen(self, search_id, keys):
            self.claimed.append((search_id, list(keys)))
            return set(keys)

    store = SearchStore()
    context = TenantContext(
        workspace_id="ws_alert_preflight",
        profile=Profile.LOCAL_SCOUT,
        territories=("TX",),
        actor_id="alert-actor",
        session_id="alert-session",
    )
    mocked_find = AsyncMock(return_value={"deals": [_deal("abc", 90)], "errors": {}})
    with (
        use_context(context),
        patch("cre_mcp.tools.pipeline_tools.get_search_store", return_value=store),
        patch("cre_mcp.tools.pipeline_tools.find_deals", new=mocked_find),
    ):
        result = await check_alerts()

    assert result == {"error": "saved search is outside the current territory"}
    assert mocked_find.await_count == 0
    assert store.claimed == []
