"""Persistent pipeline and on-demand saved-search alert MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from cre_mcp.deals.store import PIPELINE_STAGES, DealStore, get_deal_store
from cre_mcp.models import Listing
from cre_mcp.scoring.rubrics import RUBRIC_REGISTRY
from cre_mcp.tools.deal_tools import analyze_deal, find_deals

logger = logging.getLogger(__name__)

ALERT_CHECK_LIMIT = 100
ALERT_HOSTING_NOTE = (
    "This is an on-demand pull check: it runs only when check_alerts is called. "
    "True scheduled or push alerts require the always-on hosted service plus a cron/scheduler."
)


def _score_snapshot(deal: dict[str, Any]) -> tuple[float | None, str | None, str | None]:
    scores = deal.get("scores")
    if not isinstance(scores, list):
        return None, None, deal.get("best_strategy")
    valid = [item for item in scores if isinstance(item, dict)]
    preferred = deal.get("best_strategy")
    selected = next(
        (item for item in valid if item.get("strategy") == preferred),
        None,
    )
    if selected is None:
        selected = max(
            valid,
            key=lambda item: _number(item.get("score")) or 0.0,
            default=None,
        )
    if selected is None:
        return None, None, preferred
    return (
        _number(selected.get("score")),
        str(selected["grade"]) if selected.get("grade") is not None else None,
        str(selected["strategy"]) if selected.get("strategy") is not None else preferred,
    )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_key(deal: dict[str, Any]) -> str | None:
    listing = deal.get("listing")
    if not isinstance(listing, dict):
        return None
    source = str(listing.get("source") or "").strip()
    source_id = str(listing.get("source_id") or "").strip()
    if source and source_id:
        return f"{source}:{source_id}"
    url = str(listing.get("url") or "").strip()
    if url:
        return f"url:{url.casefold()}"
    address = "|".join(
        str(listing.get(key) or "").strip().casefold()
        for key in ("address", "city", "state", "zip_code")
    ).strip("|")
    return f"address:{address}" if address else None


def _validate_range(
    minimum: int | None,
    maximum: int | None,
    label: str,
) -> None:
    if minimum is not None and minimum < 0:
        raise ValueError(f"{label}_min cannot be negative")
    if maximum is not None and maximum < 0:
        raise ValueError(f"{label}_max cannot be negative")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"{label}_min cannot exceed {label}_max")


async def add_to_pipeline(
    url_or_id: str,
    source: str = "loopnet",
    stage: str = "lead",
    note: str | None = None,
) -> dict:
    """Analyze and add or refresh a listing in the persistent deal pipeline.

    Args:
        url_or_id: Source listing URL or source-specific identifier.
        source: Registered listing source. Defaults to LoopNet.
        stage: One of the supported pipeline stages; defaults to lead.
        note: Optional timestamped pipeline note.

    Returns:
        The deduped pipeline row with score snapshot and latest note.
    """
    logger.info(
        "add_to_pipeline called: source=%s listing=%s stage=%s",
        source,
        url_or_id,
        stage,
    )
    try:
        DealStore._validate_stage(stage)
        analyzed = await analyze_deal(url_or_id, source=source)
        if "error" in analyzed:
            raise ValueError(str(analyzed["error"]))
        listing = Listing.model_validate(analyzed.get("listing"))
        score, grade, strategy = _score_snapshot(analyzed)
        store = get_deal_store()
        deal_id = await store.save_deal(
            listing,
            score=score,
            grade=grade,
            strategy=strategy,
        )
        if deal_id is None:
            raise RuntimeError("deal could not be persisted; check the SQLite path and logs")
        if not await store.update_stage(deal_id, stage, note):
            raise RuntimeError(f"pipeline stage could not be updated for {deal_id}")
        row = next(
            (item for item in await store.list_pipeline() if item["deal_id"] == deal_id),
            None,
        )
        return row or {
            "deal_id": deal_id,
            "stage": stage,
            "score": score,
            "grade": grade,
            "strategy": strategy,
        }
    except Exception as exc:
        logger.error("add_to_pipeline error: %s", exc)
        return {"error": str(exc)}


async def update_deal_stage(
    deal_id: str,
    stage: str,
    note: str | None = None,
) -> dict:
    """Move a persisted deal and optionally append a timestamped note.

    Args:
        deal_id: Stable source-qualified identifier returned by save/add tools.
        stage: One of lead, analyzing, contacted, loi, under_contract,
            diligence, closing, owned, or passed.
        note: Optional note to append to the deal's history.

    Returns:
        The updated pipeline row, or an error dictionary.
    """
    logger.info("update_deal_stage called: deal=%s stage=%s", deal_id, stage)
    try:
        store = get_deal_store()
        if not await store.update_stage(deal_id, stage, note):
            raise ValueError(f"unknown deal_id: {deal_id}")
        row = next(
            (item for item in await store.list_pipeline() if item["deal_id"] == deal_id),
            None,
        )
        if row is None:
            raise RuntimeError(f"updated deal could not be read: {deal_id}")
        return row
    except Exception as exc:
        logger.error("update_deal_stage error: %s", exc)
        return {"error": str(exc)}


async def assign_deal(
    deal_id: str,
    owner: str | None = None,
    next_action: str | None = None,
    next_action_due: str | None = None,
) -> dict:
    """Assign accountability on a pipeline deal: owner, next action, due date.

    A deal with no owner, no next action, or no due date is a deal quietly
    dying — unassigned_deals and the morning queue surface exactly those. Pass
    only the fields you are setting; omitted fields are left unchanged.

    Args:
        deal_id: Source-qualified deal identifier (e.g. "crexi:2335936").
        owner: Who is responsible for moving this deal.
        next_action: The concrete next step (e.g. "send LOI", "order Phase I").
        next_action_due: Due date for the next action, ISO format YYYY-MM-DD.

    Returns:
        The updated accountability view of the deal.
    """
    logger.info("assign_deal: %s owner=%s", deal_id, owner)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        if owner is None and next_action is None and next_action_due is None:
            raise ValueError(
                "pass at least one of owner / next_action / next_action_due"
            )
        updated = await get_deal_store().assign_deal(
            deal_id.strip(),
            owner=owner,
            next_action=next_action,
            next_action_due=next_action_due,
        )
        if updated is None:
            return {"error": f"no pipeline deal with deal_id {deal_id!r} — save it first"}
        return {"assigned": updated}
    except Exception as exc:
        logger.error("assign_deal error: %s", exc)
        return {"error": str(exc)}


async def unassigned_deals() -> dict:
    """List active deals with no owner, next action, or due date (the job-3 flag).

    These are the deals most likely to die quietly: nobody owns them, nothing
    is scheduled next, or no deadline exists. Fix each one with assign_deal.

    Returns:
        Active (non-owned, non-passed) deals with their missing fields named.
    """
    logger.info("unassigned_deals called")
    try:
        rows = await get_deal_store().unaccounted_deals()
        return {
            "count": len(rows),
            "deals": rows,
            "note": "fix each with assign_deal(deal_id, owner=..., next_action=..., "
            "next_action_due=...)",
        }
    except Exception as exc:
        logger.error("unassigned_deals error: %s", exc)
        return {"error": str(exc)}


async def list_pipeline(stage: str | None = None) -> dict:
    """List all pipeline deals or filter them to one stage.

    Args:
        stage: Optional supported pipeline stage.

    Returns:
        A consistent object containing pipeline rows and count.
    """
    logger.info("list_pipeline called: stage=%s", stage)
    try:
        deals = await get_deal_store().list_pipeline(stage)
        grouped = {name: [] for name in PIPELINE_STAGES}
        for deal in deals:
            grouped.setdefault(str(deal["stage"]), []).append(deal)
        return {
            "stage": stage,
            "deals": deals,
            "by_stage": grouped,
            "count": len(deals),
        }
    except Exception as exc:
        logger.error("list_pipeline error: %s", exc)
        return {"error": str(exc)}


async def save_search(
    name: str,
    location: str,
    strategy: str | None = None,
    property_type: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    size_min: int | None = None,
    size_max: int | None = None,
    min_score: float | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Persist a named buy-box for later on-demand new-match checks.

    Args:
        name: Human-readable saved-search name.
        location: Market location accepted by find_deals.
        strategy: Optional scoring rubric.
        property_type: Optional listing property type.
        price_min: Optional minimum asking price.
        price_max: Optional maximum asking price.
        size_min: Optional minimum square feet.
        size_max: Optional maximum square feet.
        min_score: Optional minimum Medawar Deal Score from 0 through 100.
        sources: Listing sources; defaults to LoopNet.

    Returns:
        Saved-search id and query plus the pull-alert hosting disclosure.
    """
    logger.info("save_search called: name=%s location=%s", name, location)
    try:
        if not name.strip():
            raise ValueError("name cannot be blank")
        if not location.strip():
            raise ValueError("location cannot be blank")
        if strategy is not None and strategy not in RUBRIC_REGISTRY:
            raise ValueError(f"Unknown strategy: {strategy}")
        _validate_range(price_min, price_max, "price")
        _validate_range(size_min, size_max, "size")
        if min_score is not None and not 0 <= min_score <= 100:
            raise ValueError("min_score must be between 0 and 100")
        selected_sources = [item.strip() for item in (sources or ["loopnet"]) if item.strip()]
        if not selected_sources:
            raise ValueError("sources must contain at least one source")
        query = {
            "location": location.strip(),
            "strategy": strategy,
            "property_type": property_type,
            "price_min": price_min,
            "price_max": price_max,
            "size_min": size_min,
            "size_max": size_max,
            "sources": selected_sources,
        }
        search_id = await get_deal_store().save_search(name.strip(), query, min_score)
        if search_id is None:
            raise RuntimeError("saved search could not be persisted")
        return {
            "search_id": search_id,
            "name": name.strip(),
            "query": query,
            "min_score": min_score,
            "alert_mode": "pull_on_demand",
            "hosting_note": ALERT_HOSTING_NOTE,
        }
    except Exception as exc:
        logger.error("save_search error: %s", exc)
        return {"error": str(exc)}


async def list_searches() -> dict:
    """List persisted buy-boxes and how many matches each has already emitted.

    Returns:
        Saved searches plus the pull-alert hosting disclosure.
    """
    logger.info("list_searches called")
    try:
        searches = await get_deal_store().list_searches()
        return {
            "searches": searches,
            "count": len(searches),
            "alert_mode": "pull_on_demand",
            "hosting_note": ALERT_HOSTING_NOTE,
        }
    except Exception as exc:
        logger.error("list_searches error: %s", exc)
        return {"error": str(exc)}


async def check_alerts(search_id: int | None = None) -> dict:
    """Run saved searches now and emit only never-before-seen qualifying deals.

    Args:
        search_id: Optional saved-search id; omit to check every saved search.

    Returns:
        Only newly seen deals at/above each search's score floor, with pull-mode disclosure.
    """
    logger.info("check_alerts called: search_id=%s", search_id)
    try:
        store = get_deal_store()
        if search_id is not None:
            selected = await store.get_search(search_id)
            if selected is None:
                raise ValueError(f"unknown search_id: {search_id}")
            searches = [selected]
        else:
            searches = await store.list_searches()

        new_deals: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for search in searches:
            current_id = int(search["id"])
            query = dict(search["query"])
            minimum = _number(search.get("min_score"))
            location = str(query.get("location") or "").strip()
            if not location:
                message = "saved search is missing a location"
                errors[str(current_id)] = message
                results.append(
                    {
                        "search_id": current_id,
                        "name": search["name"],
                        "new_count": 0,
                        "scanned": 0,
                        "error": message,
                    }
                )
                continue
            found = await find_deals(
                location=location,
                strategy=query.get("strategy"),
                property_type=query.get("property_type"),
                price_min=query.get("price_min"),
                price_max=query.get("price_max"),
                size_min=query.get("size_min"),
                size_max=query.get("size_max"),
                sources=list(query.get("sources") or ["loopnet"]),
                min_score=minimum,
                limit=ALERT_CHECK_LIMIT,
            )
            if "error" in found:
                message = str(found["error"])
                errors[str(current_id)] = message
                results.append(
                    {
                        "search_id": current_id,
                        "name": search["name"],
                        "new_count": 0,
                        "scanned": 0,
                        "error": message,
                    }
                )
                continue

            seen = await store.seen_keys(current_id)
            candidates = found.get("deals")
            candidates = candidates if isinstance(candidates, list) else []
            unseen_rows: list[tuple[str, dict[str, Any]]] = []
            pending_keys: set[str] = set()
            for deal in candidates:
                if not isinstance(deal, dict):
                    continue
                score, _, _ = _score_snapshot(deal)
                if minimum is not None and (score is None or score < minimum):
                    continue
                key = _dedupe_key(deal)
                if key is None or key in seen or key in pending_keys:
                    continue
                pending_keys.add(key)
                unseen_rows.append((key, deal))

            await store.record_seen(current_id, [key for key, _ in unseen_rows])
            emitted: list[dict[str, Any]] = []
            for _, deal in unseen_rows:
                row = dict(deal)
                row["saved_search_id"] = current_id
                row["saved_search_name"] = search["name"]
                emitted.append(row)
            new_deals.extend(emitted)
            results.append(
                {
                    "search_id": current_id,
                    "name": search["name"],
                    "new_count": len(emitted),
                    "scanned": len(candidates),
                    "source_errors": found.get("errors", {}),
                }
            )

        return {
            "searches_checked": len(searches),
            "new_count": len(new_deals),
            "new_deals": new_deals,
            "results": results,
            "errors": errors,
            "alert_mode": "pull_on_demand",
            "hosting_note": ALERT_HOSTING_NOTE,
        }
    except Exception as exc:
        logger.error("check_alerts error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "ALERT_HOSTING_NOTE",
    "add_to_pipeline",
    "check_alerts",
    "list_pipeline",
    "list_searches",
    "save_search",
    "update_deal_stage",
]
