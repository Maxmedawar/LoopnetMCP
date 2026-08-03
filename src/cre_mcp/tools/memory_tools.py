"""MCP boundaries for the deal-graph memory layer (Phase 30).

Shadow-IC capture + a per-deal event timeline. The system logs its own verdict
independent of the expert's, so agreement — and eventually who was right once the
outcome lands — becomes measurable. This is the loop GPT-5.6's teardown called the
real moat: judgment that compounds instead of a static score.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.result_models import RestrictedDealTimelineResult
from cre_mcp.deals.store import get_deal_store

logger = logging.getLogger(__name__)


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )


def _timeline_subject_property(deal: Mapping[str, object]) -> dict[str, object]:
    listing = deal.get("listing")
    if not isinstance(listing, Mapping):
        raise ValueError("stored deal is missing its listing property")
    return {
        "address": listing.get("address"),
        "city": listing.get("city"),
        "state": listing.get("state"),
        "zip_code": listing.get("zip_code"),
    }


async def record_ic_decision(
    deal_id: str,
    system_verdict: str | None = None,
    system_notes: str | None = None,
    expert_verdict: str | None = None,
    expert_notes: str | None = None,
) -> dict:
    """Record the system's investment-committee call and (optionally) the expert's.

    Args:
        deal_id: Existing source-qualified deal identifier.
        system_verdict: The tool's call (e.g. proceed / proceed_with_conditions / re_trade / kill).
        system_notes: Optional rationale the system produced.
        expert_verdict: The human expert/committee call, if known.
        expert_notes: Optional expert rationale.

    Returns:
        The persisted decision id and whether system and expert agreed.
    """
    logger.info("record_ic_decision called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        store = get_deal_store()
        decision_id = await store.record_ic_decision(
            deal_id.strip(),
            system_verdict=system_verdict,
            system={"notes": system_notes} if system_notes else {},
            expert_verdict=expert_verdict,
            expert={"notes": expert_notes} if expert_notes else {},
        )
        if decision_id is None:
            raise ValueError(f"unknown deal_id: {deal_id}")
        agreed = None
        if system_verdict and expert_verdict:
            agreed = system_verdict.strip().casefold() == expert_verdict.strip().casefold()
        return {
            "status": "recorded",
            "decision_id": decision_id,
            "deal_id": deal_id.strip(),
            "system_verdict": system_verdict,
            "expert_verdict": expert_verdict,
            "agreed": agreed,
            "note": "Shadow-IC: this pairs with the realized outcome later to score judgment.",
        }
    except Exception as exc:
        logger.error("record_ic_decision error: %s", exc)
        return {"error": str(exc)}


async def log_deal_event(deal_id: str, event_type: str, detail: dict | None = None) -> dict:
    """Append one event to a deal's timeline (listing, contact, offer, counter, ...).

    Args:
        deal_id: Existing source-qualified deal identifier.
        event_type: Short event label (e.g. "offer", "counter", "lender_quote", "diligence_finding").
        detail: Optional structured payload for the event.

    Returns:
        The persisted event id.
    """
    logger.info("log_deal_event called: deal=%s type=%s", deal_id, event_type)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        event_id = await get_deal_store().log_deal_event(deal_id.strip(), event_type, detail)
        if event_id is None:
            raise ValueError(f"unknown deal_id: {deal_id}")
        return {"status": "logged", "event_id": event_id, "deal_id": deal_id.strip(), "event_type": event_type}
    except Exception as exc:
        logger.error("log_deal_event error: %s", exc)
        return {"error": str(exc)}


async def deal_timeline(deal_id: str) -> dict:
    """Return a deal's full event timeline plus every recorded IC decision.

    Args:
        deal_id: Source-qualified deal identifier.

    Returns:
        The ordered events and IC decisions (the deal-graph view of one deal).
    """
    logger.info("deal_timeline called: deal=%s", deal_id)
    try:
        if not deal_id or not deal_id.strip():
            raise ValueError("deal_id is required")
        normalized_deal_id = deal_id.strip()
        store = get_deal_store()
        result = await store.get_deal_timeline(normalized_deal_id)
        if not _restricted_projection_required():
            return result

        if result.get("deal_id") != normalized_deal_id:
            raise ValueError("deal timeline does not match the requested deal")
        deal = await store.get_deal(normalized_deal_id)
        if not isinstance(deal, Mapping):
            raise ValueError("unknown deal_id")
        raw_events = result.get("events")
        raw_decisions = result.get("ic_decisions")
        if type(raw_events) is not list or not all(
            isinstance(item, Mapping) for item in raw_events
        ):
            raise ValueError("deal timeline events are malformed")
        if type(raw_decisions) is not list or not all(
            isinstance(item, Mapping) for item in raw_decisions
        ):
            raise ValueError("deal timeline decisions are malformed")

        payload = {
            "deal_id": normalized_deal_id,
            "property": _timeline_subject_property(deal),
            "events": [
                {
                    "event_type": item.get("event_type"),
                    "event_ts": item.get("event_ts"),
                    "created_at": item.get("created_at"),
                }
                for item in raw_events
            ],
            "ic_decisions": [
                {
                    "system_verdict": item.get("system_verdict"),
                    "expert_verdict": item.get("expert_verdict"),
                    "agreed": item.get("agreed"),
                    "created_at": item.get("created_at"),
                }
                for item in raw_decisions
            ],
            "event_count": len(raw_events),
            "ic_decision_count": len(raw_decisions),
        }
        return RestrictedDealTimelineResult.model_validate(
            payload,
            strict=True,
        ).model_dump(mode="json")
    except Exception as exc:
        logger.error("deal_timeline error: %s", exc)
        return {"error": str(exc)}


async def ic_scorecard() -> dict:
    """Score the system's IC verdicts against experts and realized outcomes.

    Returns:
        System-vs-expert agreement rate and system-vs-outcome accuracy, both
        n-gated with an explicit caveat that small samples are directional only.
    """
    logger.info("ic_scorecard called")
    try:
        return await get_deal_store().ic_scorecard()
    except Exception as exc:
        logger.error("ic_scorecard error: %s", exc)
        return {"error": str(exc)}


__all__ = ["record_ic_decision", "log_deal_event", "deal_timeline", "ic_scorecard"]
