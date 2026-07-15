"""Durable unit-turn coordination with an explicit critical path."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


PM_TURNS_TABLE = "pm_turns"
TURN_STAGES = ("inspect", "scope", "vendor", "work", "ready")
TURN_STATUSES = frozenset(TURN_STAGES)
SCOPE_ITEM_STATUSES = frozenset({"pending", "in_progress", "complete"})
SCOPE_ITEM_FIELDS = frozenset(
    {"item", "status", "vendor", "cost_cents", "completed_date", "notes"}
)
CRITICAL_PATH_CONVENTION = (
    "Turn stages advance in this order: inspect -> scope -> vendor -> work -> ready. "
    "A bottleneck is flagged only when the recorded target is past due, a scope is "
    "missing at or after the scope stage, or a vendor is missing at or after the "
    "vendor stage. Stage labels are operational records, not field verification."
)


def _text(name: str, value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string" + (" or null" if nullable else ""))
    normalized = value.strip()
    if not normalized:
        if nullable:
            return None
        raise ValueError(f"{name} cannot be blank")
    return normalized


def _iso_date(name: str, value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO date") from exc
    else:
        raise ValueError(f"{name} must be an ISO date" + (" or null" if nullable else ""))
    return parsed.isoformat()


def _integer_cents(name: str, value: Any, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer number of cents")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _scope_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("scope_items must be a sequence of mappings")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        path = f"scope_items[{index}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path} must be a mapping")
        extras = sorted(str(key) for key in set(raw).difference(SCOPE_ITEM_FIELDS))
        if extras:
            raise ValueError(f"unrecognized inputs at {path}: {', '.join(extras)}")
        item = _text(f"{path}.item", raw.get("item"))
        status = _text(f"{path}.status", raw.get("status", "pending"))
        assert status is not None
        status = status.casefold()
        if status not in SCOPE_ITEM_STATUSES:
            raise ValueError(
                f"{path}.status must be one of: {', '.join(sorted(SCOPE_ITEM_STATUSES))}"
            )
        vendor = _text(f"{path}.vendor", raw.get("vendor"), nullable=True)
        cost_cents = _integer_cents(
            f"{path}.cost_cents", raw.get("cost_cents"), nullable=True
        )
        completed_date = _iso_date(
            f"{path}.completed_date", raw.get("completed_date"), nullable=True
        )
        if status == "complete" and completed_date is None:
            # Completion may be reported without a date; retain the distinction.
            completion_basis = "reported complete; completion date not supplied"
        elif status != "complete" and completed_date is not None:
            raise ValueError(f"{path}.completed_date requires status=complete")
        else:
            completion_basis = "recorded item status"
        notes = _text(f"{path}.notes", raw.get("notes"), nullable=True)
        normalized.append(
            {
                "item": item,
                "status": status,
                "vendor": vendor,
                "cost_cents": cost_cents,
                "completed_date": completed_date,
                "notes": notes,
                "completion_basis": completion_basis,
            }
        )
    return normalized


class TurnStore:
    """Own only the ``pm_turns`` table in a selected SQLite database."""

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
            CREATE TABLE IF NOT EXISTS pm_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unit TEXT NOT NULL,
                moveout_date TEXT NOT NULL,
                scope_items_json TEXT NOT NULL,
                vendor TEXT,
                target_ready TEXT,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(unit, moveout_date),
                CHECK(status IN ('inspect', 'scope', 'vendor', 'work', 'ready'))
            );
            CREATE INDEX IF NOT EXISTS idx_pm_turns_board
                ON pm_turns(status, target_ready, moveout_date, unit);
            """
        )
        return connection

    def record(
        self,
        unit: str,
        moveout_date: Any,
        scope_items: Sequence[Mapping[str, Any]],
        vendor: str | None = None,
        target_ready: Any = None,
        status: str = "inspect",
    ) -> dict[str, Any]:
        normalized_unit = _text("unit", unit)
        normalized_moveout = _iso_date("moveout_date", moveout_date)
        normalized_scope = _scope_items(scope_items)
        normalized_vendor = _text("vendor", vendor, nullable=True)
        normalized_target = _iso_date("target_ready", target_ready, nullable=True)
        normalized_status = _text("status", status)
        assert normalized_unit is not None
        assert normalized_moveout is not None
        assert normalized_status is not None
        normalized_status = normalized_status.casefold()
        if normalized_status not in TURN_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(TURN_STAGES)}"
            )
        if normalized_target is not None and normalized_target < normalized_moveout:
            raise ValueError("target_ready cannot precede moveout_date")
        now = datetime.now(UTC).isoformat()
        encoded_scope = json.dumps(
            normalized_scope, sort_keys=True, separators=(",", ":")
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pm_turns(
                    unit, moveout_date, scope_items_json, vendor,
                    target_ready, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit, moveout_date) DO UPDATE SET
                    scope_items_json=excluded.scope_items_json,
                    vendor=excluded.vendor,
                    target_ready=excluded.target_ready,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_unit,
                    normalized_moveout,
                    encoded_scope,
                    normalized_vendor,
                    normalized_target,
                    normalized_status,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM pm_turns WHERE unit=? AND moveout_date=?",
                (normalized_unit, normalized_moveout),
            ).fetchone()
        assert row is not None
        known_cost = sum(
            item["cost_cents"]
            for item in normalized_scope
            if item["cost_cents"] is not None
        )
        unknown_cost_count = sum(
            item["cost_cents"] is None for item in normalized_scope
        )
        return {
            "id": int(row["id"]),
            "unit": normalized_unit,
            "moveout_date": normalized_moveout,
            "scope_items": normalized_scope,
            "vendor": normalized_vendor,
            "target_ready": normalized_target,
            "status": normalized_status,
            "known_scope_cost_cents": known_cost,
            "unknown_scope_cost_count": unknown_cost_count,
            "source_ref": {"table": PM_TURNS_TABLE, "id": int(row["id"])},
            "critical_path_convention": CRITICAL_PATH_CONVENTION,
        }

    def board(self, as_of: Any = None) -> dict[str, Any]:
        cutoff_text = (
            date.today().isoformat()
            if as_of is None
            else _iso_date("as_of", as_of)
        )
        assert cutoff_text is not None
        cutoff = date.fromisoformat(cutoff_text)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, unit, moveout_date, scope_items_json,
                       vendor, target_ready, status
                FROM pm_turns
                ORDER BY moveout_date, unit, id
                """
            ).fetchall()

        turns: list[dict[str, Any]] = []
        for row in rows:
            scope = json.loads(str(row["scope_items_json"]))
            moveout = date.fromisoformat(str(row["moveout_date"]))
            target = (
                None
                if row["target_ready"] is None
                else date.fromisoformat(str(row["target_ready"]))
            )
            status = str(row["status"])
            stage_index = TURN_STAGES.index(status)
            path = [
                {
                    "stage": stage,
                    "state": (
                        "complete"
                        if index < stage_index or status == "ready"
                        else "current"
                        if index == stage_index
                        else "pending"
                    ),
                }
                for index, stage in enumerate(TURN_STAGES)
            ]
            days_vacant = max(0, (cutoff - moveout).days)
            days_past_target = (
                0 if target is None else max(0, (cutoff - target).days)
            )
            bottleneck, bottleneck_basis = _bottleneck(
                status=status,
                scope=scope,
                vendor=row["vendor"],
                target=target,
                cutoff=cutoff,
                moveout=moveout,
            )
            turns.append(
                {
                    "id": int(row["id"]),
                    "unit": str(row["unit"]),
                    "moveout_date": moveout.isoformat(),
                    "scope_items": scope,
                    "vendor": row["vendor"],
                    "target_ready": None if target is None else target.isoformat(),
                    "status": status,
                    "critical_path": path,
                    "current_stage": status,
                    "days_vacant": days_vacant,
                    "days_past_target": days_past_target,
                    "bottleneck": bottleneck,
                    "bottleneck_flag": bottleneck,
                    "bottleneck_basis": bottleneck_basis,
                    "source_ref": {"table": PM_TURNS_TABLE, "id": int(row["id"])},
                }
            )

        turns.sort(
            key=lambda item: (
                not item["bottleneck"],
                -int(item["days_past_target"]),
                -int(item["days_vacant"]),
                str(item["unit"]),
                int(item["id"]),
            )
        )
        return {
            "as_of": cutoff.isoformat(),
            "turns": turns,
            "count": len(turns),
            "bottleneck_count": sum(bool(item["bottleneck"]) for item in turns),
            "total_days_vacant": sum(int(item["days_vacant"]) for item in turns),
            "critical_path": list(TURN_STAGES),
            "critical_path_convention": CRITICAL_PATH_CONVENTION,
            "days_vacant_formula": "max(0, as_of - moveout_date) in whole calendar days",
            "honest_gap": (
                "Ready dates and stage-transition timestamps are not separate fields; "
                "days_vacant follows the requested moveout-through-as_of convention."
            ),
        }


def _bottleneck(
    *,
    status: str,
    scope: Sequence[Mapping[str, Any]],
    vendor: Any,
    target: date | None,
    cutoff: date,
    moveout: date,
) -> tuple[bool, str]:
    if moveout > cutoff:
        return False, "moveout is after as_of; vacancy clock is clamped to zero"
    if status == "ready":
        return False, "recorded status is ready"
    if target is not None and target < cutoff:
        return True, f"recorded target_ready is {(cutoff - target).days} day(s) past due"
    stage_index = TURN_STAGES.index(status)
    if stage_index >= TURN_STAGES.index("scope") and not scope:
        return True, "no scope items are recorded at or after the scope stage"
    if stage_index >= TURN_STAGES.index("vendor") and not vendor:
        return True, "no vendor is recorded at or after the vendor stage"
    return False, f"current recorded stage is {status}; no objective blocker is recorded"


def record_turn(
    unit: str,
    moveout_date: Any,
    scope_items: Sequence[Mapping[str, Any]],
    vendor: str | None = None,
    target_ready: Any = None,
    status: str = "inspect",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record or update one unit turn by unit and move-out date."""

    return TurnStore(db_path).record(
        unit,
        moveout_date,
        scope_items,
        vendor=vendor,
        target_ready=target_ready,
        status=status,
    )


def turn_board(
    as_of: Any = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the deterministic turn board for a caller-supplied cutoff date."""

    return TurnStore(db_path).board(as_of=as_of)


__all__ = [
    "CRITICAL_PATH_CONVENTION",
    "PM_TURNS_TABLE",
    "SCOPE_ITEM_FIELDS",
    "SCOPE_ITEM_STATUSES",
    "TURN_STAGES",
    "TURN_STATUSES",
    "TurnStore",
    "record_turn",
    "turn_board",
]
