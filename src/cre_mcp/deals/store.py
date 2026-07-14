"""Persistent deal and diligence state on the existing SQLite database."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from cre_mcp.config import CreConfig
from cre_mcp.models.execution import DDItem
from cre_mcp.models.listings import Listing

logger = logging.getLogger(__name__)

DD_STATUSES = frozenset({"not_started", "in_progress", "blocked", "complete", "waived"})
PIPELINE_STAGES = (
    "lead",
    "analyzing",
    "contacted",
    "loi",
    "under_contract",
    "diligence",
    "closing",
    "owned",
    "passed",
)
PIPELINE_STAGE_SET = frozenset(PIPELINE_STAGES)
OPS_STATUSES = frozenset({"not_started", "in_progress", "complete", "waived"})


class DealStore:
    """Async façade over durable deal/checklist tables in the shared cache DB."""

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
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                listing_json TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'lead',
                notes TEXT NOT NULL DEFAULT '[]',
                score REAL,
                grade TEXT,
                strategy TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_deals_source_id
                ON deals(source, source_id);

            CREATE TABLE IF NOT EXISTS outcomes (
                deal_id TEXT PRIMARY KEY,
                closed INTEGER NOT NULL,
                purchase_price REAL,
                realized_hold_years REAL,
                realized_irr REAL,
                realized_equity_multiple REAL,
                went_bad INTEGER,
                notes TEXT,
                predicted_score REAL,
                predicted_grade TEXT,
                predicted_strategy TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
                CHECK(closed IN (0, 1)),
                CHECK(went_bad IS NULL OR went_bad IN (0, 1)),
                CHECK(purchase_price IS NULL OR purchase_price > 0),
                CHECK(realized_hold_years IS NULL OR realized_hold_years > 0),
                CHECK(realized_equity_multiple IS NULL OR realized_equity_multiple >= 0)
            );
            CREATE INDEX IF NOT EXISTS idx_outcomes_updated
                ON outcomes(updated_at, deal_id);

            CREATE TABLE IF NOT EXISTS dd_items (
                deal_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_json TEXT NOT NULL,
                status TEXT NOT NULL,
                deadline TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(deal_id, item_key),
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_dd_items_deadline
                ON dd_items(deal_id, deadline);

            CREATE TABLE IF NOT EXISTS ops_events (
                deal_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                event_json TEXT NOT NULL,
                category TEXT NOT NULL,
                event_date TEXT,
                status TEXT NOT NULL DEFAULT 'not_started',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(deal_id, event_key),
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
                CHECK(category IN ('month_one', 'recurring', 'lease', 'nudge')),
                CHECK(status IN ('not_started', 'in_progress', 'complete', 'waived'))
            );
            CREATE INDEX IF NOT EXISTS idx_ops_events_date
                ON ops_events(deal_id, event_date, category);

            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                query_json TEXT NOT NULL,
                min_score REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS seen_matches (
                search_id INTEGER NOT NULL,
                dedupe_key TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                PRIMARY KEY(search_id, dedupe_key),
                FOREIGN KEY(search_id) REFERENCES saved_searches(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_seen_matches_search
                ON seen_matches(search_id, first_seen);

            CREATE TABLE IF NOT EXISTS investors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                accredited INTEGER,
                accreditation_verified INTEGER NOT NULL DEFAULT 0,
                relationship TEXT NOT NULL,
                contact_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(accredited IS NULL OR accredited IN (0, 1)),
                CHECK(accreditation_verified IN (0, 1)),
                CHECK(relationship IN ('preexisting', 'new'))
            );
            CREATE INDEX IF NOT EXISTS idx_investors_name
                ON investors(name, created_at);

            CREATE TABLE IF NOT EXISTS commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                investor_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(deal_id, investor_id),
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
                FOREIGN KEY(investor_id) REFERENCES investors(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_commitments_deal
                ON commitments(deal_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_commitments_investor
                ON commitments(investor_id, updated_at);

            CREATE TABLE IF NOT EXISTS exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                relinquished_deal_id TEXT NOT NULL,
                relinquished_close_date TEXT NOT NULL,
                identification_deadline TEXT NOT NULL,
                exchange_deadline TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(relinquished_deal_id, relinquished_close_date),
                FOREIGN KEY(relinquished_deal_id) REFERENCES deals(deal_id)
            );

            CREATE TABLE IF NOT EXISTS exchange_replacements (
                exchange_id INTEGER NOT NULL,
                deal_id TEXT NOT NULL,
                value REAL,
                identified_at TEXT NOT NULL,
                PRIMARY KEY(exchange_id, deal_id),
                FOREIGN KEY(exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_exchange_replacements_exchange
                ON exchange_replacements(exchange_id, identified_at);

            CREATE TABLE IF NOT EXISTS ic_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                system_verdict TEXT,
                system_json TEXT,
                expert_verdict TEXT,
                expert_json TEXT,
                agreed INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE,
                CHECK(agreed IS NULL OR agreed IN (0, 1))
            );
            CREATE INDEX IF NOT EXISTS idx_ic_decisions_deal
                ON ic_decisions(deal_id, created_at);

            CREATE TABLE IF NOT EXISTS deal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_json TEXT,
                event_ts TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_deal_events_deal
                ON deal_events(deal_id, event_ts, id);
            """
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(deals)").fetchall()
        }
        migrations = {
            "stage": "stage TEXT NOT NULL DEFAULT 'lead'",
            "notes": "notes TEXT NOT NULL DEFAULT '[]'",
            "score": "score REAL",
            "grade": "grade TEXT",
            "strategy": "strategy TEXT",
        }
        for name, definition in migrations.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE deals ADD COLUMN {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_deals_stage_updated ON deals(stage, updated_at)"
        )
        return connection

    @staticmethod
    def deal_id_for(listing: Listing) -> str:
        """Return the stable source-qualified identifier used across later phases."""
        source = listing.source.strip()
        source_id = listing.source_id.strip()
        if not source or not source_id:
            raise ValueError("listing source and source_id are required to save a deal")
        return f"{source}:{source_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _save_deal(
        self,
        listing: Listing,
        score: float | None,
        grade: str | None,
        strategy: str | None,
    ) -> str:
        deal_id = self.deal_id_for(listing)
        now = self._now()
        payload = listing.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO deals(
                    deal_id, source, source_id, listing_json,
                    score, grade, strategy, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET
                    listing_json = excluded.listing_json,
                    score = COALESCE(excluded.score, deals.score),
                    grade = COALESCE(excluded.grade, deals.grade),
                    strategy = COALESCE(excluded.strategy, deals.strategy),
                    updated_at = excluded.updated_at
                """,
                (
                    deal_id,
                    listing.source,
                    listing.source_id,
                    payload,
                    score,
                    grade,
                    strategy,
                    now,
                    now,
                ),
            )
        return deal_id

    async def save_deal(
        self,
        listing: Listing,
        *,
        score: float | None = None,
        grade: str | None = None,
        strategy: str | None = None,
    ) -> str | None:
        """Save or refresh a listing; persistence failure is logged, not raised."""
        try:
            return await asyncio.to_thread(
                self._save_deal,
                listing,
                score,
                grade,
                strategy,
            )
        except Exception as exc:
            logger.error("deal store save failed for %s:%s: %s", listing.source, listing.source_id, exc)
            return None

    @staticmethod
    def _decode_item(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["item_json"]))
        payload["status"] = row["status"]
        payload["deadline"] = row["deadline"]
        return payload

    def _get_deal(self, deal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT deal_id, source, source_id, listing_json,
                       stage, notes, score, grade, strategy, created_at, updated_at
                FROM deals WHERE deal_id = ?
                """,
                (deal_id,),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                """
                SELECT item_json, status, deadline
                FROM dd_items WHERE deal_id = ?
                ORDER BY deadline, item_key
                """,
                (deal_id,),
            ).fetchall()
        notes = self._decode_notes(row["notes"])
        return {
            "deal_id": row["deal_id"],
            "source": row["source"],
            "source_id": row["source_id"],
            "listing": json.loads(str(row["listing_json"])),
            "stage": row["stage"],
            "notes": notes,
            "last_note": notes[-1] if notes else None,
            "score": row["score"],
            "grade": row["grade"],
            "strategy": row["strategy"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "dd_items": [self._decode_item(item) for item in items],
        }

    async def get_deal(self, deal_id: str) -> dict[str, Any] | None:
        """Return a stored deal plus its current diligence items."""
        try:
            return await asyncio.to_thread(self._get_deal, deal_id)
        except Exception as exc:
            logger.error("deal store read failed for %s: %s", deal_id, exc)
            return None

    @staticmethod
    def _outcome_number(
        value: Any,
        label: str,
        *,
        minimum: float | None = None,
        strictly_positive: bool = False,
    ) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"{label} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite")
        if strictly_positive and number <= 0:
            raise ValueError(f"{label} must be greater than zero")
        if minimum is not None and number < minimum:
            raise ValueError(f"{label} must be at least {minimum:g}")
        return number

    @classmethod
    def _validate_outcome(cls, values: dict[str, Any]) -> dict[str, Any]:
        closed = values.get("closed")
        if not isinstance(closed, bool):
            raise ValueError("closed must be true or false")
        went_bad = values.get("went_bad")
        if went_bad is not None and not isinstance(went_bad, bool):
            raise ValueError("went_bad must be true, false, or omitted")
        purchase_price = cls._outcome_number(
            values.get("purchase_price"),
            "purchase_price",
            strictly_positive=values.get("purchase_price") is not None,
        )
        if closed and purchase_price is None:
            raise ValueError("purchase_price is required when closed=true")
        notes = values.get("notes")
        return {
            "closed": closed,
            "purchase_price": purchase_price,
            "realized_hold_years": cls._outcome_number(
                values.get("realized_hold_years"),
                "realized_hold_years",
                strictly_positive=values.get("realized_hold_years") is not None,
            ),
            "realized_irr": cls._outcome_number(
                values.get("realized_irr"),
                "realized_irr",
            ),
            "realized_equity_multiple": cls._outcome_number(
                values.get("realized_equity_multiple"),
                "realized_equity_multiple",
                minimum=0,
            ),
            "went_bad": went_bad,
            "notes": str(notes).strip() if notes is not None else None,
        }

    def _record_outcome(self, deal_id: str, values: dict[str, Any]) -> bool:
        now = self._now()
        with self._connect() as connection:
            deal = connection.execute(
                "SELECT score, grade, strategy FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if deal is None:
                return False
            connection.execute(
                """
                INSERT INTO outcomes(
                    deal_id, closed, purchase_price, realized_hold_years,
                    realized_irr, realized_equity_multiple, went_bad, notes,
                    predicted_score, predicted_grade, predicted_strategy,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET
                    closed = excluded.closed,
                    purchase_price = excluded.purchase_price,
                    realized_hold_years = excluded.realized_hold_years,
                    realized_irr = excluded.realized_irr,
                    realized_equity_multiple = excluded.realized_equity_multiple,
                    went_bad = excluded.went_bad,
                    notes = excluded.notes,
                    predicted_score = COALESCE(outcomes.predicted_score, excluded.predicted_score),
                    predicted_grade = COALESCE(outcomes.predicted_grade, excluded.predicted_grade),
                    predicted_strategy = COALESCE(outcomes.predicted_strategy, excluded.predicted_strategy),
                    updated_at = excluded.updated_at
                """,
                (
                    deal_id,
                    int(values["closed"]),
                    values["purchase_price"],
                    values["realized_hold_years"],
                    values["realized_irr"],
                    values["realized_equity_multiple"],
                    int(values["went_bad"]) if values["went_bad"] is not None else None,
                    values["notes"],
                    deal["score"],
                    deal["grade"],
                    deal["strategy"],
                    now,
                    now,
                ),
            )
        return True

    async def record_outcome(self, deal_id: str, outcome: dict[str, Any]) -> bool:
        """Upsert one realized outcome while freezing its original score snapshot."""
        normalized_id = deal_id.strip()
        if not normalized_id:
            raise ValueError("deal_id cannot be blank")
        values = self._validate_outcome(dict(outcome))
        try:
            return await asyncio.to_thread(
                self._record_outcome,
                normalized_id,
                values,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error("outcome persistence failed for %s: %s", normalized_id, exc)
            return False

    def _get_outcomes(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    o.deal_id, d.source, d.source_id,
                    o.closed, o.purchase_price, o.realized_hold_years,
                    o.realized_irr, o.realized_equity_multiple, o.went_bad,
                    o.notes, o.predicted_score, o.predicted_grade,
                    o.predicted_strategy, o.created_at, o.updated_at
                FROM outcomes o
                JOIN deals d ON d.deal_id = o.deal_id
                ORDER BY o.updated_at DESC, o.deal_id
                """
            ).fetchall()
        return [
            {
                "deal_id": row["deal_id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "closed": bool(row["closed"]),
                "purchase_price": row["purchase_price"],
                "realized_hold_years": row["realized_hold_years"],
                "realized_irr": row["realized_irr"],
                "realized_equity_multiple": row["realized_equity_multiple"],
                "went_bad": (
                    bool(row["went_bad"]) if row["went_bad"] is not None else None
                ),
                "notes": row["notes"],
                "predicted_score": row["predicted_score"],
                "predicted_grade": row["predicted_grade"],
                "predicted_strategy": row["predicted_strategy"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    async def get_outcomes(self) -> list[dict[str, Any]]:
        """Return all frozen score/outcome pairs for calibration."""
        try:
            return await asyncio.to_thread(self._get_outcomes)
        except Exception as exc:
            logger.error("outcome read failed: %s", exc)
            return []

    def _save_dd_items(self, deal_id: str, items: Iterable[DDItem]) -> bool:
        now = self._now()
        materialized = list(items)
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if exists is None:
                return False
            for item in materialized:
                previous = connection.execute(
                    "SELECT status FROM dd_items WHERE deal_id = ? AND item_key = ?",
                    (deal_id, item.key),
                ).fetchone()
                status = str(previous["status"]) if previous is not None else item.status
                persisted = item.model_copy(update={"status": status})
                connection.execute(
                    """
                    INSERT INTO dd_items(
                        deal_id, item_key, item_json, status, deadline, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deal_id, item_key) DO UPDATE SET
                        item_json = excluded.item_json,
                        status = excluded.status,
                        deadline = excluded.deadline,
                        updated_at = excluded.updated_at
                    """,
                    (
                        deal_id,
                        item.key,
                        persisted.model_dump_json(),
                        status,
                        item.deadline.isoformat(),
                        now,
                    ),
                )
            active_keys = [item.key for item in materialized]
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                connection.execute(
                    f"DELETE FROM dd_items WHERE deal_id = ? AND item_key NOT IN ({placeholders})",
                    (deal_id, *active_keys),
                )
            else:
                connection.execute("DELETE FROM dd_items WHERE deal_id = ?", (deal_id,))
        return True

    async def save_dd_items(self, deal_id: str, items: Iterable[DDItem]) -> bool:
        """Upsert a generated plan while retaining already-recorded statuses."""
        materialized = list(items)
        try:
            return await asyncio.to_thread(self._save_dd_items, deal_id, materialized)
        except Exception as exc:
            logger.error("diligence persistence failed for %s: %s", deal_id, exc)
            return False

    def _get_dd_items(self, deal_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_json, status, deadline
                FROM dd_items WHERE deal_id = ?
                ORDER BY deadline, item_key
                """,
                (deal_id,),
            ).fetchall()
        return [self._decode_item(row) for row in rows]

    async def get_dd_items(self, deal_id: str) -> list[dict[str, Any]]:
        """Return current checklist rows in deadline order."""
        try:
            return await asyncio.to_thread(self._get_dd_items, deal_id)
        except Exception as exc:
            logger.error("diligence read failed for %s: %s", deal_id, exc)
            return []

    def _save_ops_events(
        self,
        deal_id: str,
        events: list[dict[str, Any]],
    ) -> bool:
        now = self._now()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if exists is None:
                return False
            active_keys: list[str] = []
            for event in events:
                key = str(event.get("key") or "").strip()
                category = str(event.get("category") or "").strip()
                if not key:
                    raise ValueError("operating event key cannot be blank")
                if category not in {"month_one", "recurring", "lease", "nudge"}:
                    raise ValueError(f"invalid operating event category: {category}")
                previous = connection.execute(
                    "SELECT status FROM ops_events WHERE deal_id = ? AND event_key = ?",
                    (deal_id, key),
                ).fetchone()
                status = (
                    str(previous["status"])
                    if previous is not None
                    else str(event.get("status") or "not_started")
                )
                if status not in {"not_started", "in_progress", "complete", "waived"}:
                    raise ValueError(f"invalid operating event status: {status}")
                payload = {**event, "status": status}
                event_date = payload.get("event_date")
                if event_date is not None:
                    event_date = str(event_date)
                connection.execute(
                    """
                    INSERT INTO ops_events(
                        deal_id, event_key, event_json, category,
                        event_date, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deal_id, event_key) DO UPDATE SET
                        event_json = excluded.event_json,
                        category = excluded.category,
                        event_date = excluded.event_date,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        deal_id,
                        key,
                        json.dumps(payload, separators=(",", ":"), default=str),
                        category,
                        event_date,
                        status,
                        now,
                    ),
                )
                active_keys.append(key)
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                connection.execute(
                    f"DELETE FROM ops_events WHERE deal_id = ? AND event_key NOT IN ({placeholders})",
                    (deal_id, *active_keys),
                )
            else:
                connection.execute("DELETE FROM ops_events WHERE deal_id = ?", (deal_id,))
        return True

    async def save_ops_events(
        self,
        deal_id: str,
        events: Iterable[dict[str, Any]],
    ) -> bool:
        """Persist a generated operating calendar while retaining task statuses."""
        materialized = [dict(event) for event in events]
        try:
            return await asyncio.to_thread(
                self._save_ops_events,
                deal_id,
                materialized,
            )
        except ValueError:
            raise
        except Exception as exc:
            logger.error("operating-calendar persistence failed for %s: %s", deal_id, exc)
            return False

    def _get_ops_events(self, deal_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json, status, event_date
                FROM ops_events
                WHERE deal_id = ?
                ORDER BY CASE WHEN event_date IS NULL THEN 1 ELSE 0 END,
                         event_date, category, event_key
                """,
                (deal_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["event_json"]))
            payload["status"] = row["status"]
            payload["event_date"] = row["event_date"]
            events.append(payload)
        return events

    async def get_ops_events(self, deal_id: str) -> list[dict[str, Any]]:
        """Return persisted operating reminders in chronological order."""
        try:
            return await asyncio.to_thread(self._get_ops_events, deal_id)
        except Exception as exc:
            logger.error("operating-calendar read failed for %s: %s", deal_id, exc)
            return []

    def _set_ops_event_status(self, deal_id: str, key: str, status: str) -> bool:
        if status not in OPS_STATUSES:
            raise ValueError(
                f"status must be one of {', '.join(sorted(OPS_STATUSES))}"
            )
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_json FROM ops_events
                WHERE deal_id = ? AND event_key = ?
                """,
                (deal_id, key),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(str(row["event_json"]))
            payload["status"] = status
            connection.execute(
                """
                UPDATE ops_events
                SET status = ?, event_json = ?, updated_at = ?
                WHERE deal_id = ? AND event_key = ?
                """,
                (
                    status,
                    json.dumps(payload, separators=(",", ":"), default=str),
                    now,
                    deal_id,
                    key,
                ),
            )
        return True

    async def set_ops_event_status(self, deal_id: str, key: str, status: str) -> bool:
        """Update one persisted operating reminder's status."""
        return await asyncio.to_thread(
            self._set_ops_event_status,
            deal_id,
            key,
            status,
        )

    def _set_dd_item_status(self, deal_id: str, key: str, status: str) -> bool:
        if status not in DD_STATUSES:
            raise ValueError(
                f"status must be one of {', '.join(sorted(DD_STATUSES))}"
            )
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT item_json FROM dd_items
                WHERE deal_id = ? AND item_key = ?
                """,
                (deal_id, key),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(str(row["item_json"]))
            payload["status"] = status
            cursor = connection.execute(
                """
                UPDATE dd_items
                SET status = ?, item_json = ?, updated_at = ?
                WHERE deal_id = ? AND item_key = ?
                """,
                (
                    status,
                    json.dumps(payload, separators=(",", ":")),
                    now,
                    deal_id,
                    key,
                ),
            )
        return cursor.rowcount == 1

    async def set_dd_item_status(self, deal_id: str, key: str, status: str) -> bool:
        """Update one known item; invalid states are rejected, DB failures are non-fatal."""
        if status not in DD_STATUSES:
            raise ValueError(
                f"status must be one of {', '.join(sorted(DD_STATUSES))}"
            )
        try:
            return await asyncio.to_thread(self._set_dd_item_status, deal_id, key, status)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("diligence status update failed for %s/%s: %s", deal_id, key, exc)
            return False

    @staticmethod
    def _validate_stage(stage: str) -> str:
        normalized = stage.strip().casefold()
        if normalized not in PIPELINE_STAGE_SET:
            raise ValueError(
                f"stage must be one of {', '.join(PIPELINE_STAGES)}"
            )
        return normalized

    @staticmethod
    def _decode_notes(value: Any) -> list[dict[str, str]]:
        try:
            decoded = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            return []
        if not isinstance(decoded, list):
            return []
        return [item for item in decoded if isinstance(item, dict)]

    def _update_stage(
        self,
        deal_id: str,
        stage: str,
        note: str | None,
    ) -> bool:
        normalized = self._validate_stage(stage)
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT notes FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if row is None:
                return False
            notes = self._decode_notes(row["notes"])
            if note is not None and note.strip():
                notes.append(
                    {
                        "text": note.strip(),
                        "stage": normalized,
                        "created_at": now,
                    }
                )
            cursor = connection.execute(
                """
                UPDATE deals
                SET stage = ?, notes = ?, updated_at = ?
                WHERE deal_id = ?
                """,
                (
                    normalized,
                    json.dumps(notes, separators=(",", ":")),
                    now,
                    deal_id,
                ),
            )
        return cursor.rowcount == 1

    async def update_stage(
        self,
        deal_id: str,
        stage: str,
        note: str | None = None,
    ) -> bool:
        """Move a known deal and optionally append a timestamped note."""
        self._validate_stage(stage)
        try:
            return await asyncio.to_thread(self._update_stage, deal_id, stage, note)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("pipeline update failed for %s: %s", deal_id, exc)
            return False

    def _list_pipeline(self, stage: str | None) -> list[dict[str, Any]]:
        parameters: tuple[Any, ...] = ()
        where = ""
        if stage is not None:
            where = "WHERE d.stage = ?"
            parameters = (stage,)
        stage_order = " ".join(
            f"WHEN '{value}' THEN {index}"
            for index, value in enumerate(PIPELINE_STAGES)
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    d.deal_id, d.source, d.source_id, d.listing_json,
                    d.stage, d.notes, d.score, d.grade, d.strategy,
                    d.created_at, d.updated_at,
                    COUNT(i.item_key) AS dd_total,
                    SUM(CASE WHEN i.status = 'complete' THEN 1 ELSE 0 END) AS dd_complete
                FROM deals d
                LEFT JOIN dd_items i ON i.deal_id = d.deal_id
                {where}
                GROUP BY d.deal_id
                ORDER BY CASE d.stage {stage_order} ELSE 999 END,
                         d.updated_at DESC, d.deal_id
                """,
                parameters,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            listing = json.loads(str(row["listing_json"]))
            notes = self._decode_notes(row["notes"])
            results.append(
                {
                    "deal_id": row["deal_id"],
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "name": listing.get("name"),
                    "address": listing.get("address"),
                    "city": listing.get("city"),
                    "state": listing.get("state"),
                    "price_usd": listing.get("price_usd"),
                    "url": listing.get("url"),
                    "stage": row["stage"],
                    "score": row["score"],
                    "grade": row["grade"],
                    "strategy": row["strategy"],
                    "notes": notes,
                    "last_note": notes[-1] if notes else None,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "dd_total": int(row["dd_total"] or 0),
                    "dd_complete": int(row["dd_complete"] or 0),
                }
            )
        return results

    async def list_pipeline(
        self,
        stage: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return pipeline rows, optionally filtered to one validated stage."""
        normalized = self._validate_stage(stage) if stage is not None else None
        try:
            return await asyncio.to_thread(self._list_pipeline, normalized)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("pipeline list failed: %s", exc)
            return []

    def _save_search(
        self,
        name: str,
        query: dict[str, Any],
        min_score: float | None,
    ) -> int:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO saved_searches(name, query_json, min_score, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    json.dumps(query, separators=(",", ":"), default=str),
                    min_score,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    async def save_search(
        self,
        name: str,
        query: dict[str, Any],
        min_score: float | None = None,
    ) -> int | None:
        """Persist a named buy-box and return its numeric identifier."""
        if not name.strip():
            raise ValueError("search name cannot be blank")
        if not isinstance(query, dict):
            raise ValueError("search query must be a dictionary")
        try:
            return await asyncio.to_thread(self._save_search, name, query, min_score)
        except Exception as exc:
            logger.error("saved search create failed for %s: %s", name, exc)
            return None

    @staticmethod
    def _decode_search(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "query": json.loads(str(row["query_json"])),
            "min_score": row["min_score"],
            "created_at": row["created_at"],
            "seen_count": int(row["seen_count"] or 0) if "seen_count" in row.keys() else 0,
        }

    def _get_search(self, search_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.name, s.query_json, s.min_score, s.created_at,
                       COUNT(m.dedupe_key) AS seen_count
                FROM saved_searches s
                LEFT JOIN seen_matches m ON m.search_id = s.id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (search_id,),
            ).fetchone()
        return self._decode_search(row) if row is not None else None

    async def get_search(self, search_id: int) -> dict[str, Any] | None:
        """Return one saved-search record by identifier."""
        try:
            return await asyncio.to_thread(self._get_search, search_id)
        except Exception as exc:
            logger.error("saved search read failed for %s: %s", search_id, exc)
            return None

    def _list_searches(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.name, s.query_json, s.min_score, s.created_at,
                       COUNT(m.dedupe_key) AS seen_count
                FROM saved_searches s
                LEFT JOIN seen_matches m ON m.search_id = s.id
                GROUP BY s.id
                ORDER BY s.created_at, s.id
                """
            ).fetchall()
        return [self._decode_search(row) for row in rows]

    async def list_searches(self) -> list[dict[str, Any]]:
        """List saved buy-boxes with their seen-match counts."""
        try:
            return await asyncio.to_thread(self._list_searches)
        except Exception as exc:
            logger.error("saved search list failed: %s", exc)
            return []

    def _seen_keys(self, search_id: int) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT dedupe_key FROM seen_matches WHERE search_id = ?",
                (search_id,),
            ).fetchall()
        return {str(row["dedupe_key"]) for row in rows}

    async def seen_keys(self, search_id: int) -> set[str]:
        """Return the source-qualified matches already emitted for a search."""
        try:
            return await asyncio.to_thread(self._seen_keys, search_id)
        except Exception as exc:
            logger.error("seen-match read failed for search %s: %s", search_id, exc)
            return set()

    def _record_seen(self, search_id: int, keys: Iterable[str]) -> int:
        now = self._now()
        unique = sorted({key.strip() for key in keys if key and key.strip()})
        inserted = 0
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM saved_searches WHERE id = ?",
                (search_id,),
            ).fetchone()
            if exists is None:
                return 0
            for key in unique:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO seen_matches(search_id, dedupe_key, first_seen)
                    VALUES (?, ?, ?)
                    """,
                    (search_id, key, now),
                )
                inserted += max(cursor.rowcount, 0)
        return inserted

    async def record_seen(self, search_id: int, keys: Iterable[str]) -> int:
        """Record matches idempotently and return how many keys were newly inserted."""
        materialized = list(keys)
        try:
            return await asyncio.to_thread(self._record_seen, search_id, materialized)
        except Exception as exc:
            logger.error("seen-match write failed for search %s: %s", search_id, exc)
            return 0

    @staticmethod
    def _validate_investor(
        name: str,
        accredited: bool | None,
        accreditation_verified: bool,
        relationship: str,
    ) -> tuple[str, str]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("investor name cannot be blank")
        normalized_relationship = relationship.strip().casefold()
        if normalized_relationship not in {"preexisting", "new"}:
            raise ValueError("relationship must be preexisting or new")
        if accreditation_verified and accredited is not True:
            raise ValueError(
                "accreditation_verified requires accredited=True; verification cannot "
                "establish an unknown or non-accredited status"
            )
        return normalized_name, normalized_relationship

    def _add_investor(
        self,
        name: str,
        accredited: bool | None,
        accreditation_verified: bool,
        relationship: str,
        contact: dict[str, Any] | str | None,
    ) -> int:
        now = self._now()
        contact_json = (
            json.dumps(contact, separators=(",", ":"), default=str)
            if contact is not None
            else None
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO investors(
                    name, accredited, accreditation_verified, relationship,
                    contact_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    None if accredited is None else int(accredited),
                    int(accreditation_verified),
                    relationship,
                    contact_json,
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    async def add_investor(
        self,
        name: str,
        accredited: bool | None = None,
        accreditation_verified: bool = False,
        relationship: str = "new",
        contact: dict[str, Any] | str | None = None,
    ) -> int | None:
        """Persist a prospective investor and return its numeric identifier."""
        normalized_name, normalized_relationship = self._validate_investor(
            name,
            accredited,
            accreditation_verified,
            relationship,
        )
        try:
            return await asyncio.to_thread(
                self._add_investor,
                normalized_name,
                accredited,
                accreditation_verified,
                normalized_relationship,
                contact,
            )
        except Exception as exc:
            logger.error("investor create failed for %s: %s", normalized_name, exc)
            return None

    @staticmethod
    def _decode_contact(value: Any) -> dict[str, Any] | str | None:
        if value is None:
            return None
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return str(value)
        return decoded if isinstance(decoded, (dict, str)) else str(decoded)

    @classmethod
    def _decode_investor(
        cls,
        row: sqlite3.Row,
        commitments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "investor_id": int(row["id"]),
            "name": row["name"],
            "accredited": (
                None if row["accredited"] is None else bool(row["accredited"])
            ),
            "accreditation_verified": bool(row["accreditation_verified"]),
            "relationship": row["relationship"],
            "contact": cls._decode_contact(row["contact_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "commitments": commitments,
            "total_commitments": sum(float(item["amount"]) for item in commitments),
        }

    def _list_investors(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            investors = connection.execute(
                """
                SELECT id, name, accredited, accreditation_verified, relationship,
                       contact_json, created_at, updated_at
                FROM investors ORDER BY created_at, id
                """
            ).fetchall()
            commitment_rows = connection.execute(
                """
                SELECT id, deal_id, investor_id, amount, created_at, updated_at
                FROM commitments ORDER BY created_at, id
                """
            ).fetchall()
        by_investor: dict[int, list[dict[str, Any]]] = {}
        for row in commitment_rows:
            by_investor.setdefault(int(row["investor_id"]), []).append(
                {
                    "commitment_id": int(row["id"]),
                    "deal_id": row["deal_id"],
                    "investor_id": int(row["investor_id"]),
                    "amount": float(row["amount"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return [
            self._decode_investor(row, by_investor.get(int(row["id"]), []))
            for row in investors
        ]

    async def list_investors(self) -> list[dict[str, Any]]:
        """Return persisted investors and their non-binding commitments."""
        try:
            return await asyncio.to_thread(self._list_investors)
        except Exception as exc:
            logger.error("investor list failed: %s", exc)
            return []

    async def get_investor(self, investor_id: int) -> dict[str, Any] | None:
        """Return one investor record, including commitments."""
        return next(
            (
                investor
                for investor in await self.list_investors()
                if investor["investor_id"] == investor_id
            ),
            None,
        )

    def _record_commitment(
        self,
        deal_id: str,
        investor_id: int,
        amount: float,
    ) -> int | None:
        now = self._now()
        with self._connect() as connection:
            deal_exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            investor_exists = connection.execute(
                "SELECT 1 FROM investors WHERE id = ?",
                (investor_id,),
            ).fetchone()
            if deal_exists is None or investor_exists is None:
                return None
            connection.execute(
                """
                INSERT INTO commitments(
                    deal_id, investor_id, amount, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(deal_id, investor_id) DO UPDATE SET
                    amount = excluded.amount,
                    updated_at = excluded.updated_at
                """,
                (deal_id, investor_id, amount, now, now),
            )
            row = connection.execute(
                """
                SELECT id FROM commitments
                WHERE deal_id = ? AND investor_id = ?
                """,
                (deal_id, investor_id),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    async def record_commitment(
        self,
        deal_id: str,
        investor_id: int,
        amount: float,
    ) -> int | None:
        """Upsert a non-binding deal/investor capital indication."""
        try:
            normalized_amount = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError("commitment amount must be a number greater than zero") from exc
        if (
            isinstance(amount, bool)
            or not math.isfinite(normalized_amount)
            or normalized_amount <= 0
        ):
            raise ValueError("commitment amount must be greater than zero")
        try:
            return await asyncio.to_thread(
                self._record_commitment,
                deal_id,
                investor_id,
                normalized_amount,
            )
        except Exception as exc:
            logger.error(
                "commitment write failed for deal %s/investor %s: %s",
                deal_id,
                investor_id,
                exc,
            )
            return None

    async def get_commitment(self, commitment_id: int) -> dict[str, Any] | None:
        """Return one persisted non-binding commitment."""
        for investor in await self.list_investors():
            for commitment in investor["commitments"]:
                if commitment["commitment_id"] == commitment_id:
                    return commitment
        return None

    def _create_exchange(
        self,
        relinquished_deal_id: str,
        relinquished_close_date: str,
        identification_deadline: str,
        exchange_deadline: str,
    ) -> int | None:
        now = self._now()
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (relinquished_deal_id,),
            ).fetchone()
            if exists is None:
                return None
            connection.execute(
                """
                INSERT INTO exchanges(
                    relinquished_deal_id, relinquished_close_date,
                    identification_deadline, exchange_deadline,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(relinquished_deal_id, relinquished_close_date)
                DO UPDATE SET
                    identification_deadline = excluded.identification_deadline,
                    exchange_deadline = excluded.exchange_deadline,
                    updated_at = excluded.updated_at
                """,
                (
                    relinquished_deal_id,
                    relinquished_close_date,
                    identification_deadline,
                    exchange_deadline,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM exchanges
                WHERE relinquished_deal_id = ? AND relinquished_close_date = ?
                """,
                (relinquished_deal_id, relinquished_close_date),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    async def create_exchange(
        self,
        relinquished_deal_id: str,
        relinquished_close_date: str,
        identification_deadline: str,
        exchange_deadline: str,
    ) -> int | None:
        """Create or retrieve one exchange for a deal/close-date pair."""
        try:
            return await asyncio.to_thread(
                self._create_exchange,
                relinquished_deal_id,
                relinquished_close_date,
                identification_deadline,
                exchange_deadline,
            )
        except Exception as exc:
            logger.error("exchange create failed for %s: %s", relinquished_deal_id, exc)
            return None

    def _get_exchange_record(self, exchange_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, relinquished_deal_id, relinquished_close_date,
                       identification_deadline, exchange_deadline,
                       created_at, updated_at
                FROM exchanges WHERE id = ?
                """,
                (exchange_id,),
            ).fetchone()
            if row is None:
                return None
            replacements = connection.execute(
                """
                SELECT deal_id, value, identified_at
                FROM exchange_replacements
                WHERE exchange_id = ?
                ORDER BY identified_at, deal_id
                """,
                (exchange_id,),
            ).fetchall()
        return {
            "exchange_id": int(row["id"]),
            "relinquished_deal_id": row["relinquished_deal_id"],
            "relinquished_close_date": row["relinquished_close_date"],
            "identification_deadline": row["identification_deadline"],
            "exchange_deadline": row["exchange_deadline"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "replacements": [
                {
                    "deal_id": item["deal_id"],
                    "value": item["value"],
                    "identified_at": item["identified_at"],
                }
                for item in replacements
            ],
        }

    async def get_exchange_record(self, exchange_id: int) -> dict[str, Any] | None:
        """Return an exchange and its persisted identification list."""
        try:
            return await asyncio.to_thread(self._get_exchange_record, exchange_id)
        except Exception as exc:
            logger.error("exchange read failed for %s: %s", exchange_id, exc)
            return None

    def _add_exchange_replacement(
        self,
        exchange_id: int,
        deal_id: str,
        value: float | None,
        identified_at: str,
    ) -> bool:
        now = self._now()
        with self._connect() as connection:
            exchange_exists = connection.execute(
                "SELECT 1 FROM exchanges WHERE id = ?",
                (exchange_id,),
            ).fetchone()
            deal_exists = connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?",
                (deal_id,),
            ).fetchone()
            if exchange_exists is None or deal_exists is None:
                return False
            cursor = connection.execute(
                """
                INSERT INTO exchange_replacements(exchange_id, deal_id, value, identified_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(exchange_id, deal_id) DO UPDATE SET
                    value = COALESCE(excluded.value, exchange_replacements.value)
                """,
                (exchange_id, deal_id, value, identified_at),
            )
            connection.execute(
                "UPDATE exchanges SET updated_at = ? WHERE id = ?",
                (now, exchange_id),
            )
        return cursor.rowcount == 1

    async def add_exchange_replacement(
        self,
        exchange_id: int,
        deal_id: str,
        value: float | None,
        identified_at: str,
    ) -> bool:
        """Persist one candidate idempotently after service-level rule validation."""
        try:
            return await asyncio.to_thread(
                self._add_exchange_replacement,
                exchange_id,
                deal_id,
                value,
                identified_at,
            )
        except Exception as exc:
            logger.error(
                "replacement identification write failed for exchange %s/deal %s: %s",
                exchange_id,
                deal_id,
                exc,
            )
            return False

    def _list_deals(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    d.deal_id, d.source, d.source_id, d.listing_json,
                    d.stage, d.notes, d.score, d.grade, d.strategy,
                    d.created_at, d.updated_at,
                    COUNT(i.item_key) AS dd_total,
                    SUM(CASE WHEN i.status = 'complete' THEN 1 ELSE 0 END) AS dd_complete
                FROM deals d
                LEFT JOIN dd_items i ON i.deal_id = d.deal_id
                GROUP BY d.deal_id
                ORDER BY d.updated_at DESC, d.deal_id
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            listing = json.loads(str(row["listing_json"]))
            notes = self._decode_notes(row["notes"])
            results.append(
                {
                    "deal_id": row["deal_id"],
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "name": listing.get("name"),
                    "address": listing.get("address"),
                    "city": listing.get("city"),
                    "state": listing.get("state"),
                    "price_usd": listing.get("price_usd"),
                    "stage": row["stage"],
                    "score": row["score"],
                    "grade": row["grade"],
                    "strategy": row["strategy"],
                    "last_note": notes[-1] if notes else None,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "dd_total": int(row["dd_total"] or 0),
                    "dd_complete": int(row["dd_complete"] or 0),
                }
            )
        return results

    async def list_deals(self) -> list[dict[str, Any]]:
        """Return compact persisted-deal summaries, newest first."""
        try:
            return await asyncio.to_thread(self._list_deals)
        except Exception as exc:
            logger.error("deal store list failed: %s", exc)
            return []

    # --- Shadow-IC + deal-event timeline (Phase 30 memory layer) ---

    @staticmethod
    def _verdicts_agree(system_verdict: str | None, expert_verdict: str | None) -> int | None:
        if not system_verdict or not expert_verdict:
            return None
        return int(system_verdict.strip().casefold() == expert_verdict.strip().casefold())

    def _record_ic_decision(
        self,
        deal_id: str,
        system_verdict: str | None,
        system: dict[str, Any] | None,
        expert_verdict: str | None,
        expert: dict[str, Any] | None,
    ) -> int | None:
        now = self._now()
        agreed = self._verdicts_agree(system_verdict, expert_verdict)
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,)
            ).fetchone() is None:
                return None
            cursor = connection.execute(
                """
                INSERT INTO ic_decisions(
                    deal_id, system_verdict, system_json, expert_verdict,
                    expert_json, agreed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deal_id,
                    system_verdict,
                    json.dumps(system or {}, separators=(",", ":"), default=str),
                    expert_verdict,
                    json.dumps(expert or {}, separators=(",", ":"), default=str),
                    agreed,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    async def record_ic_decision(
        self,
        deal_id: str,
        *,
        system_verdict: str | None = None,
        system: dict[str, Any] | None = None,
        expert_verdict: str | None = None,
        expert: dict[str, Any] | None = None,
    ) -> int | None:
        """Capture the system's call and (optionally) the expert's, for calibration.

        The point is the SHADOW: log the system verdict before/independent of the
        expert's, so agreement — and later, who was right once the outcome lands —
        can be measured honestly.
        """
        try:
            return await asyncio.to_thread(
                self._record_ic_decision, deal_id, system_verdict, system, expert_verdict, expert
            )
        except Exception as exc:
            logger.error("ic decision write failed for %s: %s", deal_id, exc)
            return None

    def _log_event(
        self, deal_id: str, event_type: str, detail: dict[str, Any] | None, event_ts: str | None
    ) -> int | None:
        now = self._now()
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,)
            ).fetchone() is None:
                return None
            cursor = connection.execute(
                """
                INSERT INTO deal_events(deal_id, event_type, event_json, event_ts, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    deal_id,
                    event_type,
                    json.dumps(detail or {}, separators=(",", ":"), default=str),
                    event_ts or now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    async def log_deal_event(
        self,
        deal_id: str,
        event_type: str,
        detail: dict[str, Any] | None = None,
        event_ts: str | None = None,
    ) -> int | None:
        """Append one event to a deal's timeline (the deal-graph foundation)."""
        if not event_type or not event_type.strip():
            raise ValueError("event_type is required")
        try:
            return await asyncio.to_thread(
                self._log_event, deal_id, event_type.strip(), detail, event_ts
            )
        except Exception as exc:
            logger.error("deal event write failed for %s: %s", deal_id, exc)
            return None

    def _get_timeline(self, deal_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            events = connection.execute(
                """
                SELECT event_type, event_json, event_ts, created_at
                FROM deal_events WHERE deal_id = ?
                ORDER BY event_ts, id
                """,
                (deal_id,),
            ).fetchall()
            decisions = connection.execute(
                """
                SELECT system_verdict, system_json, expert_verdict, expert_json,
                       agreed, created_at
                FROM ic_decisions WHERE deal_id = ?
                ORDER BY created_at, id
                """,
                (deal_id,),
            ).fetchall()
        return {
            "deal_id": deal_id,
            "events": [
                {
                    "event_type": row["event_type"],
                    "detail": json.loads(str(row["event_json"] or "{}")),
                    "event_ts": row["event_ts"],
                    "created_at": row["created_at"],
                }
                for row in events
            ],
            "ic_decisions": [
                {
                    "system_verdict": row["system_verdict"],
                    "system": json.loads(str(row["system_json"] or "{}")),
                    "expert_verdict": row["expert_verdict"],
                    "expert": json.loads(str(row["expert_json"] or "{}")),
                    "agreed": None if row["agreed"] is None else bool(row["agreed"]),
                    "created_at": row["created_at"],
                }
                for row in decisions
            ],
        }

    async def get_deal_timeline(self, deal_id: str) -> dict[str, Any]:
        """Return a deal's full event timeline plus its recorded IC decisions."""
        try:
            return await asyncio.to_thread(self._get_timeline, deal_id)
        except Exception as exc:
            logger.error("deal timeline read failed for %s: %s", deal_id, exc)
            return {"deal_id": deal_id, "events": [], "ic_decisions": []}

    def _ic_scorecard(self) -> dict[str, Any]:
        _GO = {"proceed", "proceed_with_conditions"}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.deal_id, i.system_verdict, i.expert_verdict, i.agreed,
                       o.closed, o.went_bad
                FROM ic_decisions i
                LEFT JOIN outcomes o ON o.deal_id = i.deal_id
                WHERE i.id IN (
                    SELECT MAX(id) FROM ic_decisions GROUP BY deal_id
                )
                """
            ).fetchall()
        total = len(rows)
        with_expert = [r for r in rows if r["agreed"] is not None]
        agreed = sum(1 for r in with_expert if r["agreed"] == 1)
        scored = 0
        correct = 0
        for r in rows:
            if r["closed"] is None or not r["system_verdict"]:
                continue
            said_go = r["system_verdict"].strip().casefold() in _GO
            good = bool(r["closed"]) and not bool(r["went_bad"])
            scored += 1
            correct += int(said_go == good)
        return {
            "total_ic_decisions": total,
            "with_expert": len(with_expert),
            "system_expert_agreement_rate": round(agreed / len(with_expert), 3) if with_expert else None,
            "with_realized_outcome": scored,
            "system_accuracy_vs_outcome": round(correct / scored, 3) if scored else None,
            "caveat": (
                "Shadow-IC accuracy is only meaningful with a real sample of closed "
                "outcomes; treat small-n figures as directional, not validated."
            ),
        }

    async def ic_scorecard(self) -> dict[str, Any]:
        """Compare system verdicts to experts and to realized outcomes (honest, n-gated)."""
        try:
            return await asyncio.to_thread(self._ic_scorecard)
        except Exception as exc:
            logger.error("ic scorecard failed: %s", exc)
            return {"error": str(exc)}


def get_deal_store(config: CreConfig | None = None) -> DealStore:
    """Build a lightweight store façade over the configured shared database."""
    return DealStore(config=config or CreConfig())


__all__ = [
    "DD_STATUSES",
    "PIPELINE_STAGES",
    "PIPELINE_STAGE_SET",
    "DealStore",
    "get_deal_store",
]
