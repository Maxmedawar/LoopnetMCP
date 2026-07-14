"""Deterministic overnight brief over persisted command-center data."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from ._db import read_connection, resolve_db_path, table_exists
from ._time import as_datetime, days_left, maybe_datetime
from .snapshots import SnapshotStore
from .staleness import unattended_deals


def _transition(
    deadline: Any,
    updated_at: Any,
    point: datetime,
    since: datetime,
) -> tuple[str, int] | None:
    current_days = days_left(deadline, point)
    prior_days = days_left(deadline, since)
    if current_days is None or prior_days is None:
        return None
    updated = maybe_datetime(updated_at)
    recently_recorded = updated is not None and since < updated <= point
    if current_days < 0 <= prior_days:
        return "became_overdue", current_days
    if current_days <= 7 < prior_days:
        return "entered_7_day_window", current_days
    if current_days <= 30 < prior_days:
        return "entered_30_day_window", current_days
    if recently_recorded and current_days < 0:
        return "new_or_updated_overdue", current_days
    if recently_recorded and current_days <= 7:
        return "new_or_updated_within_7_day_window", current_days
    if recently_recorded and current_days <= 30:
        return "new_or_updated_within_30_day_window", current_days
    return None


def overnight_brief(
    as_of: date | datetime | str | None = None,
    since_hours: float = 24,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Compose persisted listing changes, deadline transitions, and attention flags.

    No LLM is used. A deadline transition means it crossed into a 30-day, 7-day,
    or overdue window during the brief interval, or was newly recorded/updated
    inside one of those windows.
    """
    if isinstance(since_hours, bool):
        raise ValueError("since_hours must be greater than zero")
    try:
        hours = float(since_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("since_hours must be greater than zero") from exc
    if hours <= 0:
        raise ValueError("since_hours must be greater than zero")
    point = as_datetime(as_of)
    since = point - timedelta(hours=hours)
    path = resolve_db_path(db_path)

    snapshot_store = SnapshotStore(path)
    changes: list[dict[str, Any]] = []
    for listing_key in snapshot_store.listing_keys():
        for event in snapshot_store.diff_snapshots(listing_key):
            captured = maybe_datetime(event.get("captured_at"))
            if captured is not None and since < captured <= point:
                changes.append(event)
    changes.sort(
        key=lambda event: (
            str(event.get("captured_at") or ""),
            str(event.get("listing_key") or ""),
            str(event.get("event_type") or ""),
        )
    )

    approaching: list[dict[str, Any]] = []
    try:
        with read_connection(path) as connection:
            if table_exists(connection, "dd_items"):
                dd_rows = connection.execute(
                    """
                    SELECT deal_id, item_key, status, deadline, updated_at
                    FROM dd_items
                    WHERE status NOT IN ('complete', 'waived')
                    ORDER BY deal_id, deadline, item_key
                    """
                ).fetchall()
                for row in dd_rows:
                    transition = _transition(
                        row["deadline"], row["updated_at"], point, since
                    )
                    if transition is None:
                        continue
                    transition_name, remaining = transition
                    approaching.append(
                        {
                            "source": "dd_item",
                            "deal_id": row["deal_id"],
                            "item_key": row["item_key"],
                            "deadline": row["deadline"],
                            "days_left": remaining,
                            "transition": transition_name,
                            "severity": "urgent" if remaining <= 7 else "important",
                        }
                    )
            if table_exists(connection, "exchanges"):
                exchange_rows = connection.execute(
                    """
                    SELECT id, relinquished_deal_id, identification_deadline,
                           exchange_deadline, updated_at
                    FROM exchanges
                    ORDER BY id
                    """
                ).fetchall()
                for row in exchange_rows:
                    for deadline_type, column in (
                        ("45_day_identification", "identification_deadline"),
                        ("180_day_exchange", "exchange_deadline"),
                    ):
                        transition = _transition(
                            row[column], row["updated_at"], point, since
                        )
                        if transition is None:
                            continue
                        transition_name, remaining = transition
                        approaching.append(
                            {
                                "source": "exchange_clock",
                                "exchange_id": int(row["id"]),
                                "deal_id": row["relinquished_deal_id"],
                                "deadline_type": deadline_type,
                                "deadline": row[column],
                                "days_left": remaining,
                                "transition": transition_name,
                                "severity": "value_destroying",
                            }
                        )
    except (FileNotFoundError, sqlite3.DatabaseError):
        # SnapshotStore can legitimately be the first component to create this DB.
        pass

    approaching.sort(
        key=lambda item: (
            int(item["days_left"]),
            0 if item["source"] == "exchange_clock" else 1,
            str(item.get("deal_id") or ""),
            str(item.get("item_key") or item.get("deadline_type") or ""),
        )
    )
    attention_result = unattended_deals(point, db_path=path)
    needs_attention = list(attention_result["deals"])
    summary_counts = {
        "listing_changes": len(changes),
        "price_changes": sum(1 for item in changes if item["event_type"] == "price_change"),
        "status_changes": sum(1 for item in changes if item["event_type"] == "status_change"),
        "broker_changes": sum(1 for item in changes if item["event_type"] == "broker_change"),
        "dom_milestones": sum(1 for item in changes if item["event_type"] == "dom_milestone"),
        "approaching_deadlines": len(approaching),
        "dd_deadline_transitions": sum(
            1 for item in approaching if item["source"] == "dd_item"
        ),
        "exchange_clock_transitions": sum(
            1 for item in approaching if item["source"] == "exchange_clock"
        ),
        "needs_attention": len(needs_attention),
    }
    return {
        "as_of": point.isoformat(),
        "since": since.isoformat(),
        "changes": changes,
        "approaching_deadlines": approaching,
        "needs_attention": needs_attention,
        "summary_counts": summary_counts,
        "note": (
            "Deterministic persisted-data brief. It sees listing snapshots, open DD, "
            "exchange clocks, pipeline stages, and logged deal events only. It does not yet "
            "see bids, document changes, inbox/calendar activity, or external listing changes "
            "that have not been captured as snapshots."
        ),
    }


__all__ = ["overnight_brief"]
