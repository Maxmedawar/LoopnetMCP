"""Deterministic flags for pipeline deals that need human attention."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from ._db import read_connection, resolve_db_path, table_exists
from ._time import as_datetime, days_left, maybe_datetime
from .queue import ACTIVE_STAGES, NEXT_ACTION

STAGE_STUCK_DAYS = {
    "lead": 10,
    "analyzing": 7,
    "contacted": 10,
    "loi": 14,
    "under_contract": 7,
    "diligence": 5,
    "closing": 3,
}


def unattended_deals(
    as_of: date | datetime | str | None = None,
    days: int = 7,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Return active deals with stale events, overdue DD, or a stuck stage.

    Stage-stuck thresholds are operational CONVENTIONS, not calibrated outcome
    predictors. ``deals.updated_at`` is only a proxy for stage-entry time because
    the existing schema does not store a dedicated stage-entered timestamp.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")
    point = as_datetime(as_of)
    path = resolve_db_path(db_path)
    empty = {
        "as_of": point.isoformat(),
        "days": days,
        "deals": [],
        "count": 0,
        "conventions": {
            "unattended_event_days": days,
            "stage_stuck_days": STAGE_STUCK_DAYS,
            "label": "CONVENTION — uncalibrated attention thresholds",
        },
    }
    if not path.exists():
        return {**empty, "note": "No command-center database exists yet."}
    try:
        with read_connection(path) as connection:
            if not table_exists(connection, "deals"):
                return {**empty, "note": "No DealStore tables exist yet."}
            rows = connection.execute(
                """
                SELECT d.deal_id, d.stage, d.created_at, d.updated_at,
                       MAX(e.event_ts) AS last_event_ts
                FROM deals d
                LEFT JOIN deal_events e ON e.deal_id = d.deal_id
                GROUP BY d.deal_id
                ORDER BY d.deal_id
                """
            ).fetchall()
            overdue_rows = connection.execute(
                """
                SELECT deal_id, item_key, deadline, status
                FROM dd_items
                WHERE status NOT IN ('complete', 'waived')
                ORDER BY deal_id, deadline, item_key
                """
            ).fetchall()
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        return {**empty, "note": f"Attention flags unavailable from persisted data: {exc}"}

    overdue: dict[str, list[dict[str, Any]]] = {}
    for item in overdue_rows:
        remaining = days_left(item["deadline"], point)
        if remaining is not None and remaining < 0:
            overdue.setdefault(str(item["deal_id"]), []).append(
                {
                    "item_key": item["item_key"],
                    "deadline": item["deadline"],
                    "days_overdue": abs(remaining),
                    "status": item["status"],
                }
            )

    results: list[dict[str, Any]] = []
    for row in rows:
        stage = str(row["stage"])
        if stage not in ACTIVE_STAGES:
            continue
        deal_id = str(row["deal_id"])
        created = maybe_datetime(row["created_at"])
        updated = maybe_datetime(row["updated_at"])
        last_event = maybe_datetime(row["last_event_ts"])
        activity_anchor = last_event or created
        inactive_days = (
            max((point - activity_anchor).days, 0) if activity_anchor is not None else None
        )
        stage_anchor = updated or created
        stage_age = max((point - stage_anchor).days, 0) if stage_anchor else None
        flags: list[dict[str, Any]] = []
        if inactive_days is None or inactive_days >= days:
            flags.append(
                {
                    "type": "no_recent_event",
                    "days_since_event": inactive_days,
                    "detail": (
                        "No deal event is recorded; age is measured from deal creation."
                        if last_event is None
                        else f"Latest deal event is {inactive_days} day(s) old."
                    ),
                }
            )
        threshold = STAGE_STUCK_DAYS[stage]
        activity_age_for_stage = inactive_days
        if (
            stage_age is not None
            and stage_age >= threshold
            and (activity_age_for_stage is None or activity_age_for_stage >= threshold)
        ):
            flags.append(
                {
                    "type": "stage_stuck",
                    "stage": stage,
                    "threshold_days": threshold,
                    "stage_age_days": stage_age,
                    "detail": (
                        "Stage age uses deals.updated_at as a proxy; no dedicated "
                        "stage-entered timestamp exists."
                    ),
                }
            )
        if deal_id in overdue:
            flags.append(
                {
                    "type": "overdue_dd",
                    "items": overdue[deal_id],
                    "detail": f"{len(overdue[deal_id])} open DD item(s) are overdue.",
                }
            )
        if not flags:
            continue
        attention = (
            "Resolve overdue DD item(s), document the disposition, and confirm whether "
            "termination or other rights remain available."
            if deal_id in overdue
            else NEXT_ACTION[stage]
        )
        results.append(
            {
                "deal_id": deal_id,
                "stage": stage,
                "last_event": row["last_event_ts"] or "no event data",
                "updated_at": row["updated_at"],
                "flags": flags,
                "attention": attention,
                "data_quality_note": (
                    "Attention is inferred only from persisted DealStore events, DD, and "
                    "stage timestamps; email/call activity not logged here is invisible."
                ),
            }
        )

    results.sort(
        key=lambda item: (
            -max(
                (
                    int(flag.get("days_since_event") or 0)
                    if flag["type"] == "no_recent_event"
                    else int(flag.get("stage_age_days") or 0)
                )
                for flag in item["flags"]
            ),
            str(item["deal_id"]),
        )
    )
    return {
        **empty,
        "deals": results,
        "count": len(results),
        "note": (
            "Flags are deterministic conventions over persisted activity; they do not prove "
            "that a deal has been ignored outside MedawarCRE."
        ),
    }


__all__ = ["STAGE_STUCK_DAYS", "unattended_deals"]
