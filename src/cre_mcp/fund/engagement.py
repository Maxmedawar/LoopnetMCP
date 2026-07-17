"""Governed investor-relations touches and honestly limited engagement framing.

The activity label in this module is deliberately not a probability model.  It is
an inspectable recency/frequency convention over recorded rows, and it stays
``UNCALIBRATED`` until realized re-up outcomes exist to calibrate it against.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cre_mcp.capital.guardrails import (
    ANTI_FRAUD_WARNING,
    reject_unsubstantiated_performance_claims,
)
from cre_mcp.config import CreConfig
from cre_mcp.execution.guardrails import capital_guardrail

TOUCH_TYPES = frozenset({"call", "email", "meeting", "distribution", "report"})
INTERACTIVE_TOUCH_TYPES = frozenset({"call", "email", "meeting"})
DELIVERY_TOUCH_TYPES = frozenset({"distribution", "report"})

UNCALIBRATED_ENGAGEMENT_WARNING = (
    "HEURISTIC - UNCALIBRATED: the re-up likelihood label is only a transparent "
    "recency/frequency activity convention. It is not a probability, prediction, "
    "recommendation, or evidence that an investor will re-up. Reports and "
    "distributions are delivery events and do not count as investor intent."
)


def _resolve_db_path(
    db_path: str | Path | CreConfig | None = None,
    *,
    config: CreConfig | None = None,
) -> Path:
    selected: str | Path | CreConfig | None = db_path if db_path is not None else config
    if isinstance(selected, CreConfig):
        path = selected.cache_db_path
    elif selected is None:
        path = CreConfig().cache_db_path
    else:
        path = Path(selected)
    return Path(path).expanduser()


def _as_utc(value: Any = None, *, label: str = "at") -> datetime:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{label} cannot be blank")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(text), datetime.min.time(), tzinfo=UTC
                )
            except ValueError as exc:
                raise ValueError(f"{label} must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_text(value: Any, label: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    if len(normalized) > 500:
        raise ValueError(f"{label} is too long")
    return normalized


def _source_ref(touch_id: int) -> dict[str, Any]:
    return {"table": "ir_touches", "id": touch_id}


def _metric(
    value: int,
    *,
    unit: str,
    sources: list[dict[str, Any]],
    formula: str,
) -> dict[str, Any]:
    return {
        "value": int(value),
        "unit": unit,
        "source_refs": sources,
        "formula": formula,
    }


class EngagementStore:
    """Own only the ``ir_touches`` table in the shared cache database."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        self.db_path = _resolve_db_path(db_path, config=config)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ir_touches (
                touch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                investor TEXT NOT NULL,
                type TEXT NOT NULL,
                at TEXT NOT NULL,
                note TEXT,
                CHECK(type IN ('call', 'email', 'meeting', 'distribution', 'report'))
            );
            CREATE INDEX IF NOT EXISTS idx_ir_touches_investor_at
                ON ir_touches(investor, at, touch_id);
            """
        )
        return connection

    def record(
        self,
        investor: str,
        touch_type: str,
        *,
        at: Any = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_investor = _required_text(investor, "investor")
        normalized_type = _required_text(touch_type, "type").casefold()
        if normalized_type not in TOUCH_TYPES:
            allowed = ", ".join(sorted(TOUCH_TYPES))
            raise ValueError(f"type must be one of: {allowed}")
        normalized_note = None if note is None else str(note).strip() or None
        if normalized_note is not None:
            if len(normalized_note) > 10_000:
                raise ValueError("note is too long")
            reject_unsubstantiated_performance_claims({"note": normalized_note})
        occurred_at = _as_utc(at)
        if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("at cannot be in the future; record a touch after it occurs")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ir_touches(investor, type, at, note)
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_investor,
                    normalized_type,
                    occurred_at.isoformat(),
                    normalized_note,
                ),
            )
        touch_id = int(cursor.lastrowid)
        return {
            "touch_id": touch_id,
            "investor": normalized_investor,
            "type": normalized_type,
            "at": occurred_at.isoformat(),
            "note": normalized_note,
            "source_ref": _source_ref(touch_id),
            "anti_fraud_warning": ANTI_FRAUD_WARNING,
            "guardrail": capital_guardrail(
                "Treat this as an internal activity record only. Counsel must approve any "
                "offering communication, re-up solicitation, subscription, or acceptance of funds."
            ),
        }

    def rows(
        self,
        *,
        investor: str | None = None,
        as_of: datetime,
    ) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if investor is None:
                return connection.execute(
                    """
                    SELECT touch_id, investor, type, at
                    FROM ir_touches
                    WHERE at <= ?
                    ORDER BY investor COLLATE NOCASE, at, touch_id
                    """,
                    (as_of.isoformat(),),
                ).fetchall()
            normalized = _required_text(investor, "investor")
            return connection.execute(
                """
                SELECT touch_id, investor, type, at
                FROM ir_touches
                WHERE investor = ? COLLATE NOCASE AND at <= ?
                ORDER BY at, touch_id
                """,
                (normalized, as_of.isoformat()),
            ).fetchall()


def record_investor_touch(
    investor: str,
    type: str,
    at: Any = None,
    note: str | None = None,
    *,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Append one governed touch; this never authorizes an investor communication."""

    return EngagementStore(db_path, config=config).record(
        investor,
        type,
        at=at,
        note=note,
    )


def _activity_score(interactive_rows: list[sqlite3.Row], as_of: datetime) -> int | None:
    if not interactive_rows:
        return None
    latest = _as_utc(interactive_rows[-1]["at"])
    recency_days = max(int((as_of - latest).total_seconds() // 86_400), 0)
    if recency_days <= 30:
        recency_points = 40
    elif recency_days <= 90:
        recency_points = 30
    elif recency_days <= 180:
        recency_points = 15
    else:
        recency_points = 0
    recent_interactive = sum(
        _as_utc(row["at"]) >= as_of - timedelta(days=180)
        for row in interactive_rows
    )
    return recency_points + min(recent_interactive, 6) * 10


def _activity_label(score: int | None) -> str:
    if score is None:
        return "insufficient governed interactive activity"
    if score >= 75:
        return "higher recorded-activity signal"
    if score >= 40:
        return "moderate recorded-activity signal"
    return "lower recorded-activity signal"


def _investor_report(rows: list[sqlite3.Row], as_of: datetime) -> dict[str, Any]:
    investor = str(rows[0]["investor"])
    refs = [_source_ref(int(row["touch_id"])) for row in rows]
    dated_rows = [(row, _as_utc(row["at"])) for row in rows]
    latest_row, latest_at = dated_rows[-1]
    by_type = Counter(str(row["type"]) for row in rows)
    interactive_rows = [
        row for row in rows if str(row["type"]) in INTERACTIVE_TOUCH_TYPES
    ]
    delivery_rows = [row for row in rows if str(row["type"]) in DELIVERY_TOUCH_TYPES]
    score = _activity_score(interactive_rows, as_of)

    frequency: dict[str, Any] = {
        "all_time": _metric(
            len(rows),
            unit="touches",
            sources=refs,
            formula="count(ir_touches rows for investor at or before as_of)",
        ),
    }
    for days in (30, 90, 365):
        selected = [
            row
            for row, occurred_at in dated_rows
            if occurred_at >= as_of - timedelta(days=days)
        ]
        frequency[f"last_{days}_days"] = _metric(
            len(selected),
            unit="touches",
            sources=[_source_ref(int(row["touch_id"])) for row in selected] or refs,
            formula=f"count(ir_touches rows within {days} days through as_of)",
        )

    type_metrics = {
        touch_type: _metric(
            count,
            unit="touches",
            sources=[
                _source_ref(int(row["touch_id"]))
                for row in rows
                if str(row["type"]) == touch_type
            ],
            formula=f"count(ir_touches rows where type={touch_type})",
        )
        for touch_type, count in sorted(by_type.items())
    }

    interactive_refs = [
        _source_ref(int(row["touch_id"])) for row in interactive_rows
    ]
    re_up: dict[str, Any] = {
        "label": _activity_label(score),
        "calibrated": False,
        "disclaimer": UNCALIBRATED_ENGAGEMENT_WARNING,
        "formula": (
            "interactive recency points (40 if <=30d, 30 if <=90d, 15 if <=180d, "
            "else 0) + 10 points per interactive touch in 180d, capped at 6; "
            "distribution/report delivery events excluded"
        ),
        "source_refs": interactive_refs,
    }
    if score is not None:
        re_up["heuristic_score"] = _metric(
            score,
            unit="uncalibrated activity points out of 100",
            sources=interactive_refs,
            formula=re_up["formula"],
        )

    return {
        "investor": investor,
        "last_touch_at": latest_at.isoformat(),
        "last_touch_source_ref": _source_ref(int(latest_row["touch_id"])),
        "recency_days": _metric(
            max(int((as_of - latest_at).total_seconds() // 86_400), 0),
            unit="days",
            sources=[_source_ref(int(latest_row["touch_id"]))],
            formula="floor(as_of - latest governed ir_touches.at)",
        ),
        "frequency": frequency,
        "by_type": type_metrics,
        "interactive_touch_count": _metric(
            len(interactive_rows),
            unit="touches",
            sources=interactive_refs or refs,
            formula="count(call, email, meeting rows); delivery events excluded",
        ),
        "delivery_event_count": _metric(
            len(delivery_rows),
            unit="events",
            sources=[_source_ref(int(row["touch_id"])) for row in delivery_rows] or refs,
            formula="count(distribution, report rows); no investor intent inferred",
        ),
        "re_up_likelihood": re_up,
        "evidence": [
            {
                "type": str(row["type"]),
                "at": str(row["at"]),
                "source_ref": _source_ref(int(row["touch_id"])),
            }
            for row in rows
        ],
    }


def engagement_report(
    investor: str | None = None,
    *,
    as_of: Any = None,
    db_path: str | Path | CreConfig | None = None,
    config: CreConfig | None = None,
) -> dict[str, Any]:
    """Frame governed touch recency/frequency without claiming predictive validity."""

    report_as_of = _as_utc(as_of, label="as_of")
    rows = EngagementStore(db_path, config=config).rows(
        investor=investor,
        as_of=report_as_of,
    )
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["investor"]), []).append(row)
    reports = [
        _investor_report(group, report_as_of)
        for _, group in sorted(grouped.items(), key=lambda item: item[0].casefold())
    ]
    unanswered = []
    if not reports:
        subject = f" for {investor.strip()}" if investor is not None else ""
        unanswered.append(
            f"No governed ir_touches rows exist{subject} at or before as_of; "
            "no engagement or re-up label was inferred."
        )
    return {
        "as_of": report_as_of.isoformat(),
        "investor_filter": investor.strip() if investor is not None else None,
        "investors": reports,
        "unanswered_questions": unanswered,
        "methodology": {
            "interactive_types": sorted(INTERACTIVE_TOUCH_TYPES),
            "delivery_types": sorted(DELIVERY_TOUCH_TYPES),
            "note": "Touch notes are not reproduced in the analytics output.",
        },
        "honesty": UNCALIBRATED_ENGAGEMENT_WARNING,
        "anti_fraud_warning": ANTI_FRAUD_WARNING,
        "guardrail": capital_guardrail(
            "Do not treat an activity label as permission to solicit, a purchaser "
            "qualification, or a re-up forecast. Have securities counsel clear each "
            "offering communication and acceptance of funds."
        ),
    }


__all__ = [
    "EngagementStore",
    "engagement_report",
    "record_investor_touch",
]
