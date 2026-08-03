"""Transparent, convention-ranked morning action queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig

from ._db import read_connection, resolve_db_path, table_exists
from ._time import as_datetime, days_left, maybe_datetime

SCORING_FORMULA = (
    "score = deadline_proximity_weight × severity_weight × deal_stage_weight"
)
DEADLINE_WEIGHTS = {
    "overdue": 5.0,
    "0_to_2_days": 4.0,
    "3_to_7_days": 3.0,
    "8_to_30_days": 2.0,
    "31_to_60_days": 1.0,
    "over_60_days": 0.5,
    "no_deadline_data": 0.25,
}
SEVERITY_WEIGHTS = {
    "value_destroying": 10.0,
    "urgent": 6.0,
    "important": 3.0,
    "routine": 1.0,
}
STAGE_WEIGHTS = {
    "lead": 0.8,
    "analyzing": 1.0,
    "contacted": 1.1,
    "loi": 1.4,
    "under_contract": 1.8,
    "diligence": 2.0,
    "closing": 2.2,
    "owned": 0.6,
    "passed": 0.2,
}
ACTIVE_STAGES = frozenset(STAGE_WEIGHTS) - {"owned", "passed"}
NEXT_ACTION = {
    "lead": "Qualify the lead and assign the next outreach step.",
    "analyzing": "Finish the initial underwriting and record a go/no-go decision.",
    "contacted": "Follow up with the broker or owner and record the response.",
    "loi": "Advance or revise the LOI and record the counterparty response.",
    "under_contract": "Confirm diligence ownership and the next contractual gate.",
    "diligence": "Resolve the next open diligence gate and preserve termination rights.",
    "closing": "Confirm closing conditions, funds, and the next critical handoff.",
}


def _deadline_weight(value: int | None) -> tuple[str, float]:
    if value is None:
        return "no_deadline_data", DEADLINE_WEIGHTS["no_deadline_data"]
    if value < 0:
        return "overdue", DEADLINE_WEIGHTS["overdue"]
    if value <= 2:
        return "0_to_2_days", DEADLINE_WEIGHTS["0_to_2_days"]
    if value <= 7:
        return "3_to_7_days", DEADLINE_WEIGHTS["3_to_7_days"]
    if value <= 30:
        return "8_to_30_days", DEADLINE_WEIGHTS["8_to_30_days"]
    if value <= 60:
        return "31_to_60_days", DEADLINE_WEIGHTS["31_to_60_days"]
    return "over_60_days", DEADLINE_WEIGHTS["over_60_days"]


def _dd_severity(value: int | None) -> str:
    if value is None:
        return "important"
    if value <= 7:
        return "urgent"
    if value <= 30:
        return "important"
    return "routine"


def _item(
    *,
    deal_id: str,
    stage: str,
    action: str,
    why: str,
    deadline: str | None,
    deadline_days: int | None,
    severity: str,
) -> dict[str, Any]:
    bucket, proximity_weight = _deadline_weight(deadline_days)
    severity_weight = SEVERITY_WEIGHTS[severity]
    stage_weight = STAGE_WEIGHTS.get(stage, 1.0)
    score = round(proximity_weight * severity_weight * stage_weight, 3)
    deadline_output = deadline if deadline is not None else "no deadline data"
    return {
        "deal_id": deal_id,
        "action": action,
        "why": why,
        "deadline": deadline_output,
        "days_left": deadline_days,
        "severity": severity,
        "score": score,
        "score_breakdown": {
            "formula": SCORING_FORMULA,
            "deadline_bucket": bucket,
            "deadline_proximity_weight": proximity_weight,
            "severity_weight": severity_weight,
            "deal_stage": stage,
            "deal_stage_weight": stage_weight,
            "calculation": (
                f"{proximity_weight:g} × {severity_weight:g} × "
                f"{stage_weight:g} = {score:g}"
            ),
        },
    }


def _empty_result(as_of: datetime, note: str) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat(),
        "queue": [],
        "count": 0,
        "scoring_formula": SCORING_FORMULA,
        "scoring_convention": {
            "label": "CONVENTION — transparent operational priority, not calibrated $ impact",
            "deadline_proximity_weights": DEADLINE_WEIGHTS,
            "severity_weights": SEVERITY_WEIGHTS,
            "deal_stage_weights": STAGE_WEIGHTS,
        },
        "note": note,
    }


def morning_action_queue(
    as_of: date | datetime | str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Build one deterministic ranked queue from persisted operational state.

    CONVENTION: ``score = deadline proximity × severity × deal stage``. Deadline
    weights are 5 overdue, 4 within 2 days, 3 within 7, 2 within 30, 1 within
    60, 0.5 later, and 0.25 when no deadline is recorded. Severity weights are
    10 value-destroying, 6 urgent, 3 important, and 1 routine. Stage weights
    range from 0.8 for lead to 2.2 for closing. These weights are operational
    conventions, not a calibrated estimate of dollar loss or close probability.

    Active deals without DD or exchange deadline data remain in the queue with
    ``deadline='no deadline data'``. Owned and passed stages are outside this
    transaction-action view.
    """
    point = as_datetime(as_of)
    path = resolve_db_path(db_path)
    if not path.exists():
        return _empty_result(point, "No command-center database exists yet; queue is empty.")

    try:
        with read_connection(path) as connection:
            if not table_exists(connection, "deals"):
                return _empty_result(
                    point,
                    "No DealStore tables exist yet; queue is empty.",
                )
            deal_rows = connection.execute(
                """
                SELECT d.deal_id, d.stage, d.created_at, d.updated_at,
                       MAX(e.event_ts) AS last_event_ts
                FROM deals d
                LEFT JOIN deal_events e ON e.deal_id = d.deal_id
                GROUP BY d.deal_id
                ORDER BY d.deal_id
                """
            ).fetchall()
            active = {
                str(row["deal_id"]): row
                for row in deal_rows
                if str(row["stage"]) in ACTIVE_STAGES
            }
            if not active:
                return _empty_result(
                    point,
                    "No active pipeline deals; owned and passed deals are not queued.",
                )

            dd_rows = connection.execute(
                """
                SELECT deal_id, item_key, item_json, status, deadline
                FROM dd_items
                WHERE status NOT IN ('complete', 'waived')
                ORDER BY deadline, deal_id, item_key
                """
            ).fetchall()
            exchange_rows = connection.execute(
                """
                SELECT e.id, e.relinquished_deal_id,
                       e.identification_deadline, e.exchange_deadline,
                       COUNT(r.deal_id) AS replacement_count
                FROM exchanges e
                LEFT JOIN exchange_replacements r ON r.exchange_id = e.id
                GROUP BY e.id
                ORDER BY e.id
                """
            ).fetchall()
            pending_ic = connection.execute(
                """
                SELECT i.deal_id, i.system_verdict, i.expert_verdict, i.created_at
                FROM ic_decisions i
                WHERE i.id = (
                    SELECT MAX(i2.id) FROM ic_decisions i2
                    WHERE i2.deal_id = i.deal_id
                )
                  AND (i.system_verdict IS NULL OR i.expert_verdict IS NULL)
                ORDER BY i.deal_id
                """
            ).fetchall()
    except (FileNotFoundError, sqlite3.DatabaseError) as exc:
        return _empty_result(point, f"Queue unavailable from persisted data: {exc}")

    items: list[dict[str, Any]] = []
    deals_with_action: set[str] = set()
    deals_with_dated_action: set[str] = set()

    for row in dd_rows:
        deal_id = str(row["deal_id"])
        if deal_id not in active:
            continue
        stage = str(active[deal_id]["stage"])
        deadline = str(row["deadline"]) if row["deadline"] else None
        remaining = days_left(deadline, point)
        label = str(row["item_key"])
        try:
            payload = json.loads(str(row["item_json"] or "{}"))
            label = str(payload.get("label") or label)
        except (TypeError, ValueError):
            pass
        malformed = deadline is not None and remaining is None
        why = (
            f"Open DD item '{label}' is {abs(remaining)} day(s) overdue."
            if remaining is not None and remaining < 0
            else f"Open DD item '{label}' has a recorded contractual/working deadline."
        )
        if malformed:
            why += " The stored deadline could not be parsed; priority uses the no-deadline convention."
        items.append(
            _item(
                deal_id=deal_id,
                stage=stage,
                action=f"Resolve DD item: {label}",
                why=why,
                deadline=deadline,
                deadline_days=remaining,
                severity=_dd_severity(remaining),
            )
        )
        deals_with_action.add(deal_id)
        if remaining is not None:
            deals_with_dated_action.add(deal_id)

    for row in exchange_rows:
        deal_id = str(row["relinquished_deal_id"])
        if deal_id not in active:
            continue
        stage = str(active[deal_id]["stage"])
        replacement_count = int(row["replacement_count"] or 0)
        for deadline_kind, column in (
            ("45-day identification", "identification_deadline"),
            ("180-day exchange", "exchange_deadline"),
        ):
            deadline = str(row[column]) if row[column] else None
            remaining = days_left(deadline, point)
            missed = remaining is not None and remaining < 0
            if deadline_kind.startswith("45"):
                action = (
                    "Escalate missed 1031 identification deadline for tax/legal review"
                    if missed
                    else "Complete and document 1031 replacement identification"
                )
                why = (
                    f"The statutory 45-day identification clock has {remaining} day(s) left; "
                    f"{replacement_count} replacement(s) are recorded. Missing it can destroy "
                    "exchange value."
                )
            else:
                action = (
                    "Escalate missed 1031 exchange deadline for tax/legal review"
                    if missed
                    else "Close a qualified 1031 replacement before the exchange deadline"
                )
                why = (
                    f"The statutory 180-day exchange clock has {remaining} day(s) left. "
                    "Missing it can destroy exchange value."
                )
            items.append(
                _item(
                    deal_id=deal_id,
                    stage=stage,
                    action=action,
                    why=why,
                    deadline=deadline,
                    deadline_days=remaining,
                    severity="value_destroying",
                )
            )
            deals_with_action.add(deal_id)
            if remaining is not None:
                deals_with_dated_action.add(deal_id)

    for row in pending_ic:
        deal_id = str(row["deal_id"])
        if deal_id not in active:
            continue
        missing = []
        if row["system_verdict"] is None:
            missing.append("system verdict")
        if row["expert_verdict"] is None:
            missing.append("expert verdict")
        items.append(
            _item(
                deal_id=deal_id,
                stage=str(active[deal_id]["stage"]),
                action="Complete the pending IC decision record",
                why=(
                    f"Latest IC record is missing {' and '.join(missing)}. "
                    "No decision deadline is stored, so urgency is convention-based."
                ),
                deadline=None,
                deadline_days=None,
                severity="important",
            )
        )
        deals_with_action.add(deal_id)

    for deal_id, row in active.items():
        last_event = maybe_datetime(row["last_event_ts"])
        created = maybe_datetime(row["created_at"])
        activity_anchor = last_event or created
        inactivity_days = (
            max((point - activity_anchor).days, 0) if activity_anchor is not None else None
        )
        if inactivity_days is not None and inactivity_days >= 7:
            evidence = (
                f"No deal event has ever been recorded; the deal is {inactivity_days} day(s) old."
                if last_event is None
                else f"The latest deal event is {inactivity_days} day(s) old."
            )
            items.append(
                _item(
                    deal_id=deal_id,
                    stage=str(row["stage"]),
                    action=NEXT_ACTION[str(row["stage"])],
                    why=(
                        f"{evidence} No action deadline is recorded for this recency flag; "
                        "the signal is based on thin persisted activity data."
                    ),
                    deadline=None,
                    deadline_days=None,
                    severity="important",
                )
            )
            deals_with_action.add(deal_id)

        if deal_id not in deals_with_action:
            has_deadline = deal_id in deals_with_dated_action
            items.append(
                _item(
                    deal_id=deal_id,
                    stage=str(row["stage"]),
                    action=NEXT_ACTION[str(row["stage"])],
                    why=(
                        "Active pipeline deal has no open DD, exchange, pending IC, or stale-event "
                        "action. No deadline data is recorded; this routine ranking is a convention."
                        if not has_deadline
                        else "Review the next pipeline action."
                    ),
                    deadline=None,
                    deadline_days=None,
                    severity="routine",
                )
            )

    items.sort(
        key=lambda item: (
            -float(item["score"]),
            item["days_left"] is None,
            item["days_left"] if item["days_left"] is not None else 10**9,
            str(item["deal_id"]),
            str(item["action"]),
        )
    )
    return {
        "as_of": point.isoformat(),
        "queue": items,
        "count": len(items),
        "scoring_formula": SCORING_FORMULA,
        "scoring_convention": {
            "label": "CONVENTION — transparent operational priority, not calibrated $ impact",
            "deadline_proximity_weights": DEADLINE_WEIGHTS,
            "severity_weights": SEVERITY_WEIGHTS,
            "deal_stage_weights": STAGE_WEIGHTS,
        },
        "note": (
            "Scores expose every multiplier. Missing deadlines remain visible as "
            "'no deadline data' and receive the 0.25 proximity convention."
        ),
    }


__all__ = [
    "DEADLINE_WEIGHTS",
    "SCORING_FORMULA",
    "SEVERITY_WEIGHTS",
    "STAGE_WEIGHTS",
    "morning_action_queue",
]
