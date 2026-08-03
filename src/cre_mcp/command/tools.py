"""Plain command-center functions for later MCP registration by the integrator."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from cre_mcp.access.context import current_context
from cre_mcp.access.profiles import TERRITORY_LIMITED
from cre_mcp.access.result_models import (
    RestrictedOvernightChangesResult,
    RestrictedStaleListingSignalsResult,
)
from cre_mcp.deals.store import DealStore
from cre_mcp.source_rights.output import safe_error_message, sanitize_payload

from .brief import overnight_brief
from .queue import morning_action_queue
from .snapshots import SnapshotStore, record_snapshot
from .stale import stale_listing_signals as infer_stale_listing_signals
from .staleness import unattended_deals

logger = logging.getLogger(__name__)


def _restricted_projection_required() -> bool:
    context = current_context()
    return bool(
        context is not None
        and not context.trusted
        and context.profile in TERRITORY_LIMITED
    )


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _subject_property(value: object, label: str) -> dict[str, object]:
    record = _required_mapping(value, label)
    zip_code = record.get("zip_code")
    if zip_code is not None:
        zip_code = _required_text(zip_code, f"{label}.zip_code")
    return {
        "address": _required_text(record.get("address"), f"{label}.address"),
        "city": _required_text(record.get("city"), f"{label}.city"),
        "state": _required_text(record.get("state"), f"{label}.state"),
        "zip_code": zip_code,
    }


def _snapshot_change_property(
    store: SnapshotStore,
    *,
    listing_key: str,
    row: Mapping[str, Any],
) -> dict[str, object]:
    from_snapshot_id = row.get("from_snapshot_id")
    to_snapshot_id = row.get("to_snapshot_id")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (from_snapshot_id, to_snapshot_id)
    ):
        raise ValueError("overnight change snapshot IDs must be integers")
    event_fields = (
        "listing_key",
        "event_type",
        "previous_captured_at",
        "captured_at",
        "from_snapshot_id",
        "to_snapshot_id",
        "direction",
        "pct_change",
        "milestone_days",
    )
    event_matches = [
        event
        for event in store.diff_snapshots(listing_key)
        if all(event.get(field) == row.get(field) for field in event_fields)
    ]
    if len(event_matches) != 1:
        raise ValueError("overnight change does not match exactly one stored event")
    snapshots = store._list_snapshots_internal(listing_key)
    matches = [
        snapshot
        for snapshot in snapshots
        if isinstance(snapshot, Mapping)
        and snapshot.get("listing_key") == listing_key
        and snapshot.get("snapshot_id") == to_snapshot_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "overnight change does not resolve to exactly one requested snapshot"
        )
    return _subject_property(matches[0].get("raw"), "snapshot.raw")


def _deal_property(
    store: DealStore,
    *,
    deal_id: str,
) -> dict[str, object]:
    deal = store._get_deal(deal_id)
    if not isinstance(deal, Mapping) or deal.get("deal_id") != deal_id:
        raise ValueError("overnight row does not resolve to its exact deal")
    return _subject_property(deal.get("listing"), "deal.listing")


def _restricted_overnight_projection(
    result: object,
) -> dict[str, Any]:
    envelope = _required_mapping(result, "overnight result")
    changes_value = envelope.get("changes")
    deadlines_value = envelope.get("approaching_deadlines")
    attention_value = envelope.get("needs_attention")
    if not isinstance(changes_value, list):
        raise ValueError("overnight result changes must be a list")
    if not isinstance(deadlines_value, list):
        raise ValueError("overnight result approaching_deadlines must be a list")
    if not isinstance(attention_value, list):
        raise ValueError("overnight result needs_attention must be a list")

    snapshot_store = SnapshotStore()
    deal_store = DealStore()
    projected_changes: list[dict[str, object]] = []
    for index, value in enumerate(changes_value):
        row = _required_mapping(value, f"changes[{index}]")
        listing_key = _required_text(
            row.get("listing_key"), f"changes[{index}].listing_key"
        )
        projected_changes.append(
            {
                "property": _snapshot_change_property(
                    snapshot_store,
                    listing_key=listing_key,
                    row=row,
                ),
                "event_type": _required_text(
                    row.get("event_type"), f"changes[{index}].event_type"
                ),
                "previous_captured_at": _optional_text(
                    row.get("previous_captured_at"),
                    f"changes[{index}].previous_captured_at",
                ),
                "captured_at": _optional_text(
                    row.get("captured_at"), f"changes[{index}].captured_at"
                ),
                "from_snapshot_id": row.get("from_snapshot_id"),
                "to_snapshot_id": row.get("to_snapshot_id"),
                "direction": _optional_text(
                    row.get("direction"), f"changes[{index}].direction"
                ),
                "pct_change": row.get("pct_change"),
                "milestone_days": row.get("milestone_days"),
            }
        )

    projected_deadlines: list[dict[str, object]] = []
    for index, value in enumerate(deadlines_value):
        row = _required_mapping(value, f"approaching_deadlines[{index}]")
        deal_id = _required_text(
            row.get("deal_id"), f"approaching_deadlines[{index}].deal_id"
        )
        projected_deadlines.append(
            {
                "property": _deal_property(deal_store, deal_id=deal_id),
                "source": _required_text(
                    row.get("source"), f"approaching_deadlines[{index}].source"
                ),
                "deadline": _required_text(
                    row.get("deadline"), f"approaching_deadlines[{index}].deadline"
                ),
                "days_left": row.get("days_left"),
                "transition": _required_text(
                    row.get("transition"),
                    f"approaching_deadlines[{index}].transition",
                ),
                "severity": _required_text(
                    row.get("severity"), f"approaching_deadlines[{index}].severity"
                ),
            }
        )

    projected_attention: list[dict[str, object]] = []
    for index, value in enumerate(attention_value):
        row = _required_mapping(value, f"needs_attention[{index}]")
        deal_id = _required_text(
            row.get("deal_id"), f"needs_attention[{index}].deal_id"
        )
        flags = row.get("flags")
        if not isinstance(flags, list) or not flags:
            raise ValueError(f"needs_attention[{index}].flags must be a non-empty list")
        flag_types: list[str] = []
        for flag_index, flag_value in enumerate(flags):
            flag = _required_mapping(
                flag_value, f"needs_attention[{index}].flags[{flag_index}]"
            )
            flag_types.append(
                _required_text(
                    flag.get("type"),
                    f"needs_attention[{index}].flags[{flag_index}].type",
                )
            )
        projected_attention.append(
            {
                "property": _deal_property(deal_store, deal_id=deal_id),
                "stage": _required_text(
                    row.get("stage"), f"needs_attention[{index}].stage"
                ),
                "flag_types": flag_types,
            }
        )

    summary_counts = {
        "listing_changes": len(projected_changes),
        "price_changes": sum(
            row["event_type"] == "price_change" for row in projected_changes
        ),
        "status_changes": sum(
            row["event_type"] == "status_change" for row in projected_changes
        ),
        "broker_changes": sum(
            row["event_type"] == "broker_change" for row in projected_changes
        ),
        "dom_milestones": sum(
            row["event_type"] == "dom_milestone" for row in projected_changes
        ),
        "approaching_deadlines": len(projected_deadlines),
        "dd_deadline_transitions": sum(
            row["source"] == "dd_item" for row in projected_deadlines
        ),
        "exchange_clock_transitions": sum(
            row["source"] == "exchange_clock" for row in projected_deadlines
        ),
        "needs_attention": len(projected_attention),
    }
    return RestrictedOvernightChangesResult.model_validate(
        {
            "as_of": envelope.get("as_of"),
            "since": envelope.get("since"),
            "changes": projected_changes,
            "deadlines": projected_deadlines,
            "attention": projected_attention,
            "summary_counts": summary_counts,
        }
    ).model_dump(mode="json")


def _restricted_stale_projection(
    requested_listing_key: str,
    snapshots: object,
    result: object,
) -> dict[str, Any]:
    requested_key = _required_text(requested_listing_key, "listing_key")
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("restricted stale-listing inference requires snapshots")
    latest = _required_mapping(snapshots[-1], "latest snapshot")
    if latest.get("listing_key") != requested_key:
        raise ValueError("latest snapshot does not match the requested listing_key")
    envelope = _required_mapping(result, "stale-listing result")
    if envelope.get("listing_key") != requested_key:
        raise ValueError("stale-listing result does not match the requested listing_key")

    evidence = _required_mapping(envelope.get("evidence"), "stale evidence")
    snapshot_count = evidence.get("snapshot_count")
    if (
        isinstance(snapshot_count, bool)
        or not isinstance(snapshot_count, int)
        or snapshot_count != len(snapshots)
    ):
        raise ValueError("stale evidence snapshot_count does not match the store")
    convention = _required_mapping(envelope.get("convention"), "stale convention")
    score_rules = _required_mapping(
        convention.get("score_rules"), "stale convention score_rules"
    )
    return RestrictedStaleListingSignalsResult.model_validate(
        {
            "listing_key": requested_key,
            "property": _subject_property(latest.get("raw"), "latest snapshot.raw"),
            "negotiability_signal": envelope.get("negotiability_signal"),
            "heuristic_score": envelope.get("heuristic_score"),
            "evidence": {
                "snapshot_count": snapshot_count,
                "latest_dom": evidence.get("latest_dom"),
                "price_cut_count": evidence.get("price_cut_count"),
                "price_cut_velocity_per_30_days": evidence.get(
                    "price_cut_velocity_per_30_days"
                ),
                "cumulative_price_change_pct": evidence.get(
                    "cumulative_price_change_pct"
                ),
                "observation_days": evidence.get("observation_days"),
            },
            "convention": {
                "stale_dom_days": convention.get("stale_dom_days"),
                "very_stale_dom_days": convention.get("very_stale_dom_days"),
                "score_rules": {
                    "dom_90_to_179": score_rules.get("dom_90_to_179"),
                    "dom_180_plus": score_rules.get("dom_180_plus"),
                    "one_price_cut": score_rules.get("one_price_cut"),
                    "two_plus_price_cuts": score_rules.get("two_plus_price_cuts"),
                    "one_plus_cuts_per_30_days": score_rules.get(
                        "one_plus_cuts_per_30_days"
                    ),
                    "two_plus_cuts_per_30_days": score_rules.get(
                        "two_plus_cuts_per_30_days"
                    ),
                },
            },
            "thin_data": envelope.get("thin_data"),
        }
    ).model_dump(mode="json")


def morning_queue(as_of: Any = None) -> dict[str, Any]:
    """Return today's transparent, convention-ranked action queue."""
    logger.info("morning_queue called: as_of=%s", safe_error_message(as_of))
    try:
        return morning_action_queue(as_of)
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("morning_queue error: %s", message)
        return {"error": message}


def overnight_changes(since_hours: float = 24) -> dict[str, Any]:
    """Return the deterministic persisted-data change brief."""
    logger.info("overnight_changes called: since_hours=%s", since_hours)
    try:
        result = overnight_brief(since_hours=since_hours)
        if _restricted_projection_required():
            return _restricted_overnight_projection(result)
        return result
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("overnight_changes error: %s", message)
        return {"error": message}


def flag_unattended(days: int = 7) -> dict[str, Any]:
    """Flag active deals with no recent event, overdue DD, or a stuck stage."""
    logger.info("flag_unattended called: days=%s", days)
    try:
        return unattended_deals(days=days)
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("flag_unattended error: %s", message)
        return {"error": message}


def record_listing_snapshot(listing: dict[str, Any]) -> dict[str, Any]:
    """Record one listing snapshot without making a network request."""
    logger.info("record_listing_snapshot called")
    try:
        return record_snapshot(listing)
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("record_listing_snapshot error: %s", message)
        return {"error": message}


def stale_listing_signals(listing_key: str) -> dict[str, Any]:
    """Return explicitly uncalibrated stale/negotiability signals for one listing."""
    safe_listing_key = safe_error_message(listing_key)
    logger.info("stale_listing_signals called: listing_key=%s", safe_listing_key)
    try:
        snapshot_store = SnapshotStore()
        snapshots = (
            snapshot_store._list_snapshots_internal(listing_key)
            if _restricted_projection_required()
            else snapshot_store.list_snapshots(listing_key)
        )
        result = infer_stale_listing_signals(snapshots)
        if _restricted_projection_required():
            return _restricted_stale_projection(listing_key, snapshots, result)
        if result["listing_key"] is None:
            result["listing_key"] = listing_key
        return sanitize_payload(result)
    except Exception as exc:
        message = safe_error_message(exc)
        logger.error("stale_listing_signals error: %s", message)
        return {"error": message}


__all__ = [
    "flag_unattended",
    "morning_queue",
    "overnight_changes",
    "record_listing_snapshot",
    "stale_listing_signals",
]
