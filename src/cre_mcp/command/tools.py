"""Plain command-center functions for later MCP registration by the integrator."""

from __future__ import annotations

import logging
from typing import Any

from .brief import overnight_brief
from .queue import morning_action_queue
from .snapshots import SnapshotStore, record_snapshot
from .stale import stale_listing_signals as infer_stale_listing_signals
from .staleness import unattended_deals

logger = logging.getLogger(__name__)


def morning_queue(as_of: Any = None) -> dict[str, Any]:
    """Return today's transparent, convention-ranked action queue."""
    logger.info("morning_queue called: as_of=%s", as_of)
    try:
        return morning_action_queue(as_of)
    except Exception as exc:
        logger.error("morning_queue error: %s", exc)
        return {"error": str(exc)}


def overnight_changes(since_hours: float = 24) -> dict[str, Any]:
    """Return the deterministic persisted-data change brief."""
    logger.info("overnight_changes called: since_hours=%s", since_hours)
    try:
        return overnight_brief(since_hours=since_hours)
    except Exception as exc:
        logger.error("overnight_changes error: %s", exc)
        return {"error": str(exc)}


def flag_unattended(days: int = 7) -> dict[str, Any]:
    """Flag active deals with no recent event, overdue DD, or a stuck stage."""
    logger.info("flag_unattended called: days=%s", days)
    try:
        return unattended_deals(days=days)
    except Exception as exc:
        logger.error("flag_unattended error: %s", exc)
        return {"error": str(exc)}


def record_listing_snapshot(listing: dict[str, Any]) -> dict[str, Any]:
    """Record one listing snapshot without making a network request."""
    logger.info("record_listing_snapshot called")
    try:
        return record_snapshot(listing)
    except Exception as exc:
        logger.error("record_listing_snapshot error: %s", exc)
        return {"error": str(exc)}


def stale_listing_signals(listing_key: str) -> dict[str, Any]:
    """Return explicitly uncalibrated stale/negotiability signals for one listing."""
    logger.info("stale_listing_signals called: listing_key=%s", listing_key)
    try:
        snapshots = SnapshotStore().list_snapshots(listing_key)
        result = infer_stale_listing_signals(snapshots)
        if result["listing_key"] is None:
            result["listing_key"] = listing_key
        return result
    except Exception as exc:
        logger.error("stale_listing_signals error: %s", exc)
        return {"error": str(exc)}


__all__ = [
    "flag_unattended",
    "morning_queue",
    "overnight_changes",
    "record_listing_snapshot",
    "stale_listing_signals",
]
