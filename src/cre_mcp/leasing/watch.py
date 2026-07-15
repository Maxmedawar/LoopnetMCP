"""Durable manual and tool-fed tenant signals for leasing screens.

Only the ``leasing_watch`` table is owned here.  Automated news, ratings, and
store-count feeds are intentionally outside this substrate.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig


SIGNAL_TYPES = frozenset(
    {"closure_news", "credit_downgrade", "store_count_change", "manual_note"}
)
SEVERITIES = frozenset({"info", "low", "medium", "moderate", "high", "critical"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leasing_watch (
    tenant_name TEXT NOT NULL,
    category TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    CHECK(signal_type IN ('closure_news', 'credit_downgrade', 'store_count_change', 'manual_note')),
    CHECK(severity IN ('info', 'low', 'medium', 'moderate', 'high', 'critical'))
);
CREATE INDEX IF NOT EXISTS idx_leasing_watch_tenant_history
    ON leasing_watch(tenant_name COLLATE NOCASE, recorded_at);
"""

_SUBSTRATE_NOTE = (
    "Substrate only: manual and tool-fed signals accrue here. Automated closure-news, "
    "credit-rating, and store-count feeds are a later phase; an absent signal is not "
    "evidence of tenant health or renewal intent."
)


def _nonblank(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} cannot be blank")
    return normalized


def _timestamp(value: Any = None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        text = _nonblank(value, "recorded_at")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(text), datetime.min.time(), tzinfo=UTC
                )
            except ValueError as exc:
                raise ValueError("recorded_at must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


class LeasingWatchStore:
    """Append and read signals while owning only ``leasing_watch``."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        if isinstance(db_path, CreConfig):
            resolved = db_path.cache_db_path
        else:
            resolved = db_path or (config or CreConfig()).cache_db_path
        self.db_path = Path(resolved).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(_SCHEMA)
        return connection

    def record_tenant_signal(
        self,
        tenant_name: str,
        category: str,
        signal_type: str,
        severity: str,
        note: str,
        recorded_at: Any = None,
    ) -> dict[str, Any]:
        tenant = _nonblank(tenant_name, "tenant_name")
        normalized_category = _nonblank(category, "category")
        normalized_type = _nonblank(signal_type, "signal_type").casefold()
        normalized_severity = _nonblank(severity, "severity").casefold()
        normalized_note = _nonblank(note, "note")
        if normalized_type not in SIGNAL_TYPES:
            raise ValueError(
                "signal_type must be one of: " + ", ".join(sorted(SIGNAL_TYPES))
            )
        if normalized_severity not in SEVERITIES:
            raise ValueError(
                "severity must be one of: " + ", ".join(sorted(SEVERITIES))
            )
        timestamp = _timestamp(recorded_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO leasing_watch(
                    tenant_name, category, signal_type, severity, note, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    normalized_category,
                    normalized_type,
                    normalized_severity,
                    normalized_note,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT tenant_name, category, signal_type, severity, note, recorded_at
                FROM leasing_watch WHERE rowid=?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        assert row is not None
        return {
            **dict(row),
            "signal_label": "structured input; not independently verified",
            "substrate_note": _SUBSTRATE_NOTE,
        }

    def tenant_watch_report(self, tenant: str) -> dict[str, Any]:
        normalized_tenant = _nonblank(tenant, "tenant")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT tenant_name, category, signal_type, severity, note, recorded_at
                FROM leasing_watch
                WHERE tenant_name = ? COLLATE NOCASE
                ORDER BY recorded_at ASC, rowid ASC
                """,
                (normalized_tenant,),
            ).fetchall()
        history = [
            {
                **dict(row),
                "signal_label": "structured input; not independently verified",
            }
            for row in rows
        ]

        severity_counts = {severity: 0 for severity in sorted(SEVERITIES)}
        signal_type_counts = {signal_type: 0 for signal_type in sorted(SIGNAL_TYPES)}
        for signal in history:
            severity_counts[str(signal["severity"])] += 1
            signal_type_counts[str(signal["signal_type"])] += 1

        adverse = [
            signal
            for signal in history
            if signal["signal_type"] in {"closure_news", "credit_downgrade"}
        ]
        severity_rank = {
            "info": 0,
            "low": 1,
            "medium": 2,
            "moderate": 2,
            "high": 3,
            "critical": 4,
        }
        highest_adverse = max(
            (severity_rank[str(signal["severity"])] for signal in adverse),
            default=None,
        )
        if not history:
            risk_label = "unassessed_no_recorded_signals"
            basis = "No signals are recorded for this tenant."
        elif highest_adverse is None:
            risk_label = "unassessed_review_recorded_context"
            basis = (
                "Only store-count-change and/or manual-note context is recorded; "
                "direction is not inferred from free text."
            )
        elif highest_adverse >= 3:
            risk_label = "elevated_review"
            basis = (
                "At least one recorded closure-news or credit-downgrade input has "
                "high or critical severity."
            )
        elif highest_adverse == 2:
            risk_label = "monitor"
            basis = (
                "At least one recorded closure-news or credit-downgrade input has "
                "medium/moderate severity."
            )
        else:
            risk_label = "limited_recorded_adverse_context"
            basis = (
                "Recorded closure-news or credit-downgrade inputs are info/low severity."
            )

        risk_framing = {
            "label": risk_label,
            "basis": basis,
            "classification": "screening convention over recorded structured inputs",
            "rule": (
                "Only closure_news and credit_downgrade affect the label; high/critical "
                "maps to elevated_review, medium/moderate to monitor, and info/low to "
                "limited_recorded_adverse_context. Store-count direction and manual notes "
                "require human review."
            ),
            "limitations": (
                "This is renewal-risk framing, not a credit opinion, verified news finding, "
                "probability of renewal, or assertion that a tenant will sign."
            ),
        }
        return {
            "tenant": normalized_tenant,
            "tenant_name": normalized_tenant,
            "signal_count": len(history),
            "signals": history,
            "history": [dict(signal) for signal in history],
            "severity_counts": severity_counts,
            "signal_type_counts": signal_type_counts,
            "renewal_risk_framing": risk_framing,
            "renewal_risk": dict(risk_framing),
            "risk_level": risk_label,
            "substrate_status": "manual_and_tool_fed_only",
            "substrate_note": _SUBSTRATE_NOTE,
            "automated_feeds": {
                "status": "later_phase",
                "included_now": False,
                "feed_types": [
                    "closure_news",
                    "credit_ratings",
                    "store_count_changes",
                ],
            },
            "database_path": str(self.db_path),
        }


def record_tenant_signal(
    tenant_name: str,
    category: str,
    signal_type: str,
    severity: str,
    note: str,
    recorded_at: Any = None,
    *,
    config: CreConfig | None = None,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Append one user- or tool-supplied signal."""

    return LeasingWatchStore(db_path, config=config).record_tenant_signal(
        tenant_name, category, signal_type, severity, note, recorded_at
    )


def tenant_watch_report(
    tenant: str,
    *,
    config: CreConfig | None = None,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Return deterministic signal history and cautious renewal-risk framing."""

    return LeasingWatchStore(db_path, config=config).tenant_watch_report(tenant)


__all__ = [
    "LeasingWatchStore",
    "SEVERITIES",
    "SIGNAL_TYPES",
    "record_tenant_signal",
    "tenant_watch_report",
]
