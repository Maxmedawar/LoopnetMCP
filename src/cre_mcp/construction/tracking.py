"""Durable construction-control log for RFIs, submittals, and field gates."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


CX_ITEMS_TABLE = "cx_items"
ITEM_TYPES = frozenset({"rfi", "submittal", "procurement", "inspection"})
TYPE_CLOSED_STATUSES: dict[str, frozenset[str]] = {
    "rfi": frozenset({"answered", "closed", "complete", "completed", "cancelled"}),
    "submittal": frozenset({"approved", "approved_as_noted", "closed", "complete", "completed", "cancelled"}),
    "procurement": frozenset({"delivered", "released", "closed", "complete", "completed", "cancelled"}),
    "inspection": frozenset({"passed", "final", "closed", "complete", "completed", "cancelled"}),
}
CLOSED_STATUSES = frozenset().union(*TYPE_CLOSED_STATUSES.values())


def _text(name: str, value: Any) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _iso_date(name: str, value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(_text(name, value))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date") from exc
    return parsed.isoformat()


def _as_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _review_flags(item_type: str) -> list[str]:
    base = ["GC/CM: confirm ownership, response date, and schedule impact."]
    if item_type in {"rfi", "submittal"}:
        base.append("architect/engineer: provide and document the formal design response.")
    if item_type == "procurement":
        base.append("architect/engineer: confirm approved product; GC must validate lead time.")
    if item_type == "inspection":
        base.append("inspector/AHJ: record the actual inspection result; log status is not approval.")
    return base


def _structured_review_flags() -> dict[str, bool]:
    return {
        "gc_review_required": True,
        "architect_review_required": True,
        "engineer_review_required": True,
        "inspector_review_required": True,
    }


class ConstructionTrackingStore:
    """Own only the ``cx_items`` table in a selected SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved = db_path or Path.home() / ".cache" / "cre_mcp" / "cache.db"
        self.db_path = Path(resolved).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cx_items (
                project TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('rfi', 'submittal', 'procurement', 'inspection')),
                ref TEXT NOT NULL,
                opened TEXT NOT NULL,
                due TEXT NOT NULL,
                status TEXT NOT NULL,
                critical INTEGER NOT NULL CHECK(critical IN (0, 1)),
                updated_at TEXT NOT NULL,
                PRIMARY KEY(project, type, ref)
            );
            CREATE INDEX IF NOT EXISTS idx_cx_items_due
                ON cx_items(project, critical, due, status);
            """
        )
        return connection

    def record(
        self,
        project: str,
        item_type: str,
        ref: str,
        opened: Any,
        due: Any,
        status: str,
        critical: bool,
    ) -> dict[str, Any]:
        normalized_project = _text("project", project)
        normalized_type = _text("type", item_type).casefold()
        if normalized_type not in ITEM_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(ITEM_TYPES))}")
        normalized_ref = _text("ref", ref)
        opened_date = _iso_date("opened", opened)
        due_date = _iso_date("due", due)
        if due_date < opened_date:
            raise ValueError("due cannot precede opened")
        normalized_status = _text("status", status).casefold()
        critical_value = _as_bool("critical", critical)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cx_items(
                    project, type, ref, opened, due, status, critical, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, type, ref) DO UPDATE SET
                    opened=excluded.opened,
                    due=excluded.due,
                    status=excluded.status,
                    critical=excluded.critical,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_project,
                    normalized_type,
                    normalized_ref,
                    opened_date,
                    due_date,
                    normalized_status,
                    int(critical_value),
                    now,
                ),
            )
        return {
            "project": normalized_project,
            "type": normalized_type,
            "ref": normalized_ref,
            "opened": opened_date,
            "due": due_date,
            "status": normalized_status,
            "critical": critical_value,
            "evidence_basis": "register-reported; not approval or field verification",
            "professional_review_flags": _review_flags(normalized_type),
            "review_flags": _structured_review_flags(),
        }

    def list_items(
        self,
        project: str,
        item_type: str | None = None,
        status: str | None = None,
        critical: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project=?"]
        values: list[Any] = [_text("project", project)]
        if item_type is not None:
            normalized_type = _text("type", item_type).casefold()
            if normalized_type not in ITEM_TYPES:
                raise ValueError(f"type must be one of: {', '.join(sorted(ITEM_TYPES))}")
            clauses.append("type=?")
            values.append(normalized_type)
        if status is not None:
            clauses.append("status=?")
            values.append(_text("status", status).casefold())
        if critical is not None:
            clauses.append("critical=?")
            values.append(int(_as_bool("critical", critical)))
        query = (
            "SELECT project, type, ref, opened, due, status, critical "
            f"FROM cx_items WHERE {' AND '.join(clauses)} ORDER BY due, type, ref"
        )
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [
            {
                "project": row["project"],
                "type": row["type"],
                "ref": row["ref"],
                "opened": row["opened"],
                "due": row["due"],
                "status": row["status"],
                "critical": bool(row["critical"]),
                "evidence_basis": "register-reported; not approval or field verification",
                "professional_review_flags": _review_flags(row["type"]),
                "review_flags": _structured_review_flags(),
            }
            for row in rows
        ]

    def slippage(self, project: str, as_of: Any = None) -> dict[str, Any]:
        cutoff = date.today() if as_of is None else date.fromisoformat(_iso_date("as_of", as_of))
        items = self.list_items(project, critical=True)
        overdue: list[dict[str, Any]] = []
        for item in items:
            due = date.fromisoformat(item["due"])
            if item["status"] in TYPE_CLOSED_STATUSES[item["type"]] or due >= cutoff:
                continue
            overdue.append(
                {
                    **item,
                    "as_of": cutoff.isoformat(),
                    "days_late": (cutoff - due).days,
                    "flag": "OPEN CRITICAL ITEM PAST DUE",
                }
            )
        return {
            "project": _text("project", project),
            "as_of": cutoff.isoformat(),
            "open_critical_past_due": overdue,
            "count": len(overdue),
            "maximum_days_late": max((item["days_late"] for item in overdue), default=0),
            "schedule_basis": (
                "register due-date comparison only; GC/CM must validate actual critical-path impact"
            ),
            "professional_review_flags": [
                "GC/CM: validate whether each late item controls the current CPM schedule.",
                "architect/engineer: expedite overdue design responses and approvals.",
                "inspector/AHJ: confirm inspection availability and actual approvals.",
            ],
            "review_flags": _structured_review_flags(),
        }


# Alias consistent with shorter store names elsewhere in the codebase.
TrackingStore = ConstructionTrackingStore


def record_item(
    project: str,
    item_type: str,
    ref: str,
    opened: Any,
    due: Any,
    status: str,
    critical: bool,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return ConstructionTrackingStore(db_path).record(
        project, item_type, ref, opened, due, status, critical
    )


def track_items(
    project: str,
    item_type: str | None = None,
    status: str | None = None,
    critical: bool | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    items = ConstructionTrackingStore(db_path).list_items(
        project, item_type=item_type, status=status, critical=critical
    )
    return {"project": _text("project", project), "count": len(items), "items": items}


def critical_path_slippage(
    project: str,
    as_of: Any = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    return ConstructionTrackingStore(db_path).slippage(project, as_of=as_of)


def record_tracking_item(
    item: Mapping[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Mapping-friendly record boundary with an explicit, non-variadic signature."""

    if not isinstance(item, Mapping):
        raise ValueError("item must be a mapping")
    return record_item(
        item.get("project"),
        item.get("type"),
        item.get("ref"),
        item.get("opened"),
        item.get("due"),
        item.get("status"),
        item.get("critical"),
        db_path,
    )


__all__ = [
    "CLOSED_STATUSES",
    "CX_ITEMS_TABLE",
    "ConstructionTrackingStore",
    "ITEM_TYPES",
    "TrackingStore",
    "TYPE_CLOSED_STATUSES",
    "critical_path_slippage",
    "record_item",
    "record_tracking_item",
    "track_items",
]
