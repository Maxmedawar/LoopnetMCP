"""Durable data-room inventory and transparent completeness scoring."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore
from cre_mcp.truth.models import DocKind
from cre_mcp.truth.store import TruthStore

from .taxonomy import PHASES, get_taxonomy

ITEM_STATUSES = frozenset(
    {"missing", "requested", "received", "reviewed", "issue_found"}
)
PHASE_ORDER = {phase: index for index, phase in enumerate(PHASES)}

# Weight says how much one in-scope document contributes to the denominator.
# Credit says how complete that document is at its present workflow status.
PHASE_WEIGHTS: dict[str, float] = {
    "loi": 1.0,
    "diligence": 3.0,
    "financing": 2.0,
    "closing": 3.0,
}
STATUS_CREDITS: dict[str, float] = {
    "missing": 0.0,
    "requested": 0.10,
    "received": 0.70,
    "reviewed": 1.0,
    "issue_found": 0.25,
}
COMPLETENESS_FORMULA = (
    "100 * sum(phase_weight[item.phase] * status_credit[item.status]) / "
    "sum(phase_weight[item.phase]) for required items through current_phase "
    "plus conditional items through current_phase whose status is not missing"
)

# TruthStore currently classifies only broad document kinds.  These matches
# prove kind-level receipt, not completeness, execution, freshness, tenant
# coverage, or satisfactory review.
DOC_KIND_TO_DOC_KEYS: dict[str, tuple[str, ...]] = {
    DocKind.OM.value: ("offering_memorandum",),
    DocKind.RENT_ROLL.value: ("rent_roll",),
    DocKind.T12.value: ("t12_operating_statement",),
    DocKind.LEASE.value: ("all_leases",),
    DocKind.AMENDMENT.value: ("lease_amendments",),
    DocKind.ESTOPPEL.value: ("estoppels", "farm_tenant_estoppels"),
    DocKind.TAX_BILL.value: ("tax_bills", "property_tax_bills"),
    DocKind.APPRAISAL.value: ("appraisal",),
    DocKind.SURVEY.value: ("alta_survey",),
}
DOC_KEY_TO_DOC_KIND: dict[str, str] = {
    doc_key: doc_kind
    for doc_kind, doc_keys in DOC_KIND_TO_DOC_KEYS.items()
    for doc_key in doc_keys
}

_STAGE_TO_PHASE = {
    "lead": "loi",
    "analyzing": "loi",
    "contacted": "loi",
    "loi": "loi",
    "under_contract": "diligence",
    "diligence": "diligence",
    "financing": "financing",
    "closing": "closing",
    "owned": "closing",
    "passed": "loi",
}
_UNSET = object()


def _timestamp(value: Any = None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("as_of cannot be blank")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)
            except ValueError as exc:
                raise ValueError("as_of must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _due_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("due_date must be an ISO date") from exc


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


class DataRoomStore:
    """Own only data-room tables in the shared cache SQLite database."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        # DealStore is used only for its established path-resolution contract.
        self.db_path = DealStore(db_path or config).db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dataroom_items (
                deal_id TEXT NOT NULL,
                doc_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'missing',
                assignee TEXT,
                due_date TEXT,
                source_document_id TEXT,
                notes TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(deal_id, doc_key),
                CHECK(status IN ('missing', 'requested', 'received', 'reviewed', 'issue_found'))
            );
            CREATE INDEX IF NOT EXISTS idx_dataroom_items_due
                ON dataroom_items(deal_id, due_date, doc_key);

            CREATE TABLE IF NOT EXISTS completeness_index (
                deal_id TEXT PRIMARY KEY,
                deal_type TEXT NOT NULL,
                as_of TEXT NOT NULL,
                score REAL,
                current_phase TEXT,
                blockers_json TEXT NOT NULL DEFAULT '[]',
                formula_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        return connection

    @staticmethod
    def _validate_deal_id(deal_id: str) -> str:
        normalized = str(deal_id).strip()
        if not normalized:
            raise ValueError("deal_id cannot be blank")
        return normalized

    def init_data_room(
        self,
        deal_id: str,
        deal_type: str,
        *,
        as_of: Any = None,
    ) -> dict[str, Any]:
        """Initialize taxonomy rows without erasing previously recorded progress."""

        normalized_id = self._validate_deal_id(deal_id)
        taxonomy = get_taxonomy(deal_type)
        normalized_type = deal_type.strip().casefold()
        now = _timestamp(as_of)
        inserted = 0
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT deal_type FROM completeness_index WHERE deal_id=?",
                (normalized_id,),
            ).fetchone()
            if existing is not None and str(existing["deal_type"]) != normalized_type:
                raise ValueError(
                    f"data room already uses deal_type={existing['deal_type']}; "
                    "changing taxonomy would make historical completeness incomparable"
                )
            connection.execute(
                """
                INSERT INTO completeness_index(deal_id, deal_type, as_of)
                VALUES (?, ?, ?)
                ON CONFLICT(deal_id) DO UPDATE SET as_of=excluded.as_of
                """,
                (normalized_id, normalized_type, now),
            )
            for requirement in taxonomy:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO dataroom_items(
                        deal_id, doc_key, status, assignee, due_date,
                        source_document_id, notes, updated_at
                    ) VALUES (?, ?, 'missing', NULL, NULL, NULL, NULL, ?)
                    """,
                    (normalized_id, requirement["doc_key"], now),
                )
                inserted += cursor.rowcount
        return {
            "deal_id": normalized_id,
            "deal_type": normalized_type,
            "taxonomy_item_count": len(taxonomy),
            "inserted_item_count": inserted,
            "preserved_existing_items": len(taxonomy) - inserted,
            "as_of": now,
            "taxonomy": [dict(item) for item in taxonomy],
            "convention": (
                "Required rows are graded; conditional rows are ungraded until their "
                "trigger is known to apply through a non-missing status."
            ),
        }

    def _metadata(self, connection: sqlite3.Connection, deal_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT deal_type, as_of FROM completeness_index WHERE deal_id=?",
            (deal_id,),
        ).fetchone()

    def update_item(
        self,
        deal_id: str,
        doc_key: str,
        *,
        status: str | object = _UNSET,
        assignee: str | None | object = _UNSET,
        due_date: Any = _UNSET,
        notes: str | None | object = _UNSET,
        source_document_id: str | None | object = _UNSET,
    ) -> dict[str, Any]:
        """Patch one known row; omitted fields remain unchanged."""

        normalized_id = self._validate_deal_id(deal_id)
        normalized_key = str(doc_key).strip()
        if not normalized_key:
            raise ValueError("doc_key cannot be blank")
        assignments: list[str] = []
        values: list[Any] = []
        if status is not _UNSET:
            normalized_status = str(status).strip().casefold()
            if normalized_status not in ITEM_STATUSES:
                allowed = ", ".join(sorted(ITEM_STATUSES))
                raise ValueError(f"status must be one of: {allowed}")
            assignments.append("status=?")
            values.append(normalized_status)
        if assignee is not _UNSET:
            normalized_assignee = None if assignee is None else str(assignee).strip() or None
            assignments.append("assignee=?")
            values.append(normalized_assignee)
        if due_date is not _UNSET:
            assignments.append("due_date=?")
            values.append(_due_date(due_date))
        if notes is not _UNSET:
            normalized_notes = None if notes is None else str(notes).strip() or None
            assignments.append("notes=?")
            values.append(normalized_notes)
        if source_document_id is not _UNSET:
            normalized_source = (
                None
                if source_document_id is None
                else str(source_document_id).strip() or None
            )
            assignments.append("source_document_id=?")
            values.append(normalized_source)
        if not assignments:
            raise ValueError("at least one item field must be supplied")
        now = _timestamp()
        assignments.append("updated_at=?")
        values.append(now)
        values.extend((normalized_id, normalized_key))
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE dataroom_items SET {', '.join(assignments)} "
                "WHERE deal_id=? AND doc_key=?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown data-room item: {normalized_id}/{normalized_key}")
            row = connection.execute(
                "SELECT * FROM dataroom_items WHERE deal_id=? AND doc_key=?",
                (normalized_id, normalized_key),
            ).fetchone()
        assert row is not None
        return dict(row)

    def _auto_match(self, connection: sqlite3.Connection, deal_id: str) -> list[dict[str, Any]]:
        """Promote kind-matched missing/requested rows to received, read-only from TruthStore."""

        # Resolve through TruthStore's public constructor, but never call its
        # schema-creating connection method or write its tables.
        truth_path = TruthStore(CreConfig(cache_db_path=self.db_path)).db_path
        if truth_path != self.db_path or not _table_exists(connection, "truth_documents"):
            return []
        documents = connection.execute(
            """
            SELECT document_id, doc_kind, parse_status, ingested_at
            FROM truth_documents
            WHERE deal_id=?
            ORDER BY ingested_at DESC, document_id
            """,
            (deal_id,),
        ).fetchall()
        matched: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        now = _timestamp()
        for document in documents:
            for doc_key in DOC_KIND_TO_DOC_KEYS.get(str(document["doc_kind"]), ()):
                if doc_key in seen_keys:
                    continue
                row = connection.execute(
                    """
                    SELECT status FROM dataroom_items
                    WHERE deal_id=? AND doc_key=?
                    """,
                    (deal_id, doc_key),
                ).fetchone()
                if row is None:
                    continue
                seen_keys.add(doc_key)
                if str(row["status"]) not in {"missing", "requested"}:
                    continue
                connection.execute(
                    """
                    UPDATE dataroom_items
                    SET status='received', source_document_id=?, updated_at=?
                    WHERE deal_id=? AND doc_key=?
                    """,
                    (document["document_id"], now, deal_id, doc_key),
                )
                matched.append(
                    {
                        "doc_key": doc_key,
                        "doc_kind": document["doc_kind"],
                        "source_document_id": document["document_id"],
                        "parse_status": document["parse_status"],
                        "match_basis": "TruthStore doc_kind convention",
                    }
                )
        return matched

    @staticmethod
    def _current_phase(connection: sqlite3.Connection, deal_id: str) -> tuple[str, str | None, str]:
        if not _table_exists(connection, "deals"):
            return "loi", None, "convention: no deals table; earliest phase assumed"
        row = connection.execute(
            "SELECT stage FROM deals WHERE deal_id=?",
            (deal_id,),
        ).fetchone()
        if row is None:
            return "loi", None, "convention: deal not found; earliest phase assumed"
        stage = str(row["stage"]).strip().casefold()
        phase = _STAGE_TO_PHASE.get(stage, "loi")
        source = "DealStore deals.stage mapping"
        if stage not in _STAGE_TO_PHASE:
            source = f"convention: unrecognized stage {stage!r}; earliest phase assumed"
        return phase, stage, source

    def completeness_index(self, deal_id: str, *, as_of: Any = None) -> dict[str, Any]:
        """Auto-match truth documents, score in-scope rows, and persist the snapshot."""

        normalized_id = self._validate_deal_id(deal_id)
        as_of_text = _timestamp(as_of)
        with self._connect() as connection:
            metadata = self._metadata(connection, normalized_id)
            if metadata is None:
                return {
                    "deal_id": normalized_id,
                    "initialized": False,
                    "deal_type": None,
                    "as_of": as_of_text,
                    "score": None,
                    "current_phase": None,
                    "items": [],
                    "blockers": [],
                    "unassigned_gaps": [],
                    "note": "No data-room taxonomy has been initialized for this deal.",
                    "formula": self.formula_disclosure(),
                }
            deal_type = str(metadata["deal_type"])
            taxonomy = get_taxonomy(deal_type)
            auto_matches = self._auto_match(connection, normalized_id)
            rows = connection.execute(
                """
                SELECT deal_id, doc_key, status, assignee, due_date,
                       source_document_id, notes, updated_at
                FROM dataroom_items WHERE deal_id=? ORDER BY doc_key
                """,
                (normalized_id,),
            ).fetchall()
            stored_by_key = {str(row["doc_key"]): dict(row) for row in rows}
            current_phase, deal_stage, phase_source = self._current_phase(
                connection, normalized_id
            )
            current_rank = PHASE_ORDER[current_phase]
            items: list[dict[str, Any]] = []
            blockers: list[dict[str, Any]] = []
            unassigned_gaps: list[dict[str, Any]] = []
            conditional_not_activated: list[dict[str, Any]] = []
            earned = 0.0
            possible = 0.0
            for requirement in taxonomy:
                stored = stored_by_key.get(requirement["doc_key"])
                if stored is None:
                    # Honest even if a database was partially initialized.
                    stored = {
                        "deal_id": normalized_id,
                        "doc_key": requirement["doc_key"],
                        "status": "missing",
                        "assignee": None,
                        "due_date": None,
                        "source_document_id": None,
                        "notes": "taxonomy row absent from persistence",
                        "updated_at": None,
                    }
                status = str(stored["status"])
                conditional_active = requirement["required"] or status != "missing"
                in_phase = PHASE_ORDER[requirement["phase"]] <= current_rank
                graded = in_phase and conditional_active
                weight = PHASE_WEIGHTS[requirement["phase"]]
                credit = STATUS_CREDITS[status]
                if graded:
                    possible += weight
                    earned += weight * credit
                item = {
                    **requirement,
                    **stored,
                    "conditional_active": conditional_active,
                    "in_current_phase_scope": in_phase,
                    "graded": graded,
                    "weight": weight if graded else 0.0,
                    "status_credit": credit if graded else 0.0,
                    "weighted_credit": weight * credit if graded else 0.0,
                    "auto_match_doc_kind": DOC_KEY_TO_DOC_KIND.get(requirement["doc_key"]),
                }
                items.append(item)
                if not requirement["required"] and not conditional_active:
                    conditional_not_activated.append(
                        {
                            "doc_key": requirement["doc_key"],
                            "label": requirement["label"],
                            "trigger": requirement["trigger"],
                        }
                    )
                if graded and status in {"missing", "requested", "issue_found"}:
                    gap = {
                        "doc_key": requirement["doc_key"],
                        "label": requirement["label"],
                        "phase": requirement["phase"],
                        "status": status,
                        "assignee": stored["assignee"],
                        "due_date": stored["due_date"],
                        "what_missing_costs": requirement["what_missing_costs"],
                    }
                    if stored["assignee"] is None:
                        unassigned_gaps.append(gap)
                    if requirement["phase"] == current_phase:
                        blockers.append(
                            {
                                **gap,
                                "reason": (
                                    "unresolved_issue"
                                    if status == "issue_found"
                                    else "not_received"
                                ),
                            }
                        )
            score = round(100.0 * earned / possible, 2) if possible else None
            formula = self.formula_disclosure()
            connection.execute(
                """
                UPDATE completeness_index
                SET as_of=?, score=?, current_phase=?, blockers_json=?, formula_json=?
                WHERE deal_id=?
                """,
                (
                    as_of_text,
                    score,
                    current_phase,
                    json.dumps(blockers, separators=(",", ":"), default=str),
                    json.dumps(formula, separators=(",", ":"), default=str),
                    normalized_id,
                ),
            )
        return {
            "deal_id": normalized_id,
            "initialized": True,
            "deal_type": deal_type,
            "taxonomy_name": f"cre_mcp.dataroom.{deal_type}.v1",
            "taxonomy_item_count": len(taxonomy),
            "as_of": as_of_text,
            "deal_stage": deal_stage,
            "current_phase": current_phase,
            "current_phase_source": phase_source,
            "score": score,
            "earned_weighted_points": round(earned, 4),
            "possible_weighted_points": round(possible, 4),
            "formula": formula,
            "items": items,
            "blockers": blockers,
            "unassigned_gaps": unassigned_gaps,
            "conditional_not_activated": conditional_not_activated,
            "auto_matches": auto_matches,
            "auto_match_limit": (
                "A match proves only that at least one ingested document has the mapped "
                "TruthStore kind; it does not prove a complete set, correct version, "
                "execution, freshness, tenant coverage, or satisfactory review."
            ),
        }

    @staticmethod
    def formula_disclosure() -> dict[str, Any]:
        return {
            "formula": COMPLETENESS_FORMULA,
            "phase_weights": dict(PHASE_WEIGHTS),
            "status_credits": dict(STATUS_CREDITS),
            "phase_gating": "Only taxonomy phases up to and including current_phase are graded.",
            "conditional_gating": (
                "A conditional item is excluded while status=missing; requested, received, "
                "reviewed, or issue_found means its trigger is treated as active."
            ),
            "score_interpretation": (
                "Workflow completeness against the named taxonomy, not legal sufficiency, "
                "document accuracy, or investment quality."
            ),
        }


def completeness_index(
    deal_id: str,
    deal_type: str | None = None,
    as_of: Any = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Convenience entry point; optionally initialize a previously unknown deal."""

    store = DataRoomStore(db_path)
    if deal_type is not None:
        store.init_data_room(deal_id, deal_type, as_of=as_of)
    return store.completeness_index(deal_id, as_of=as_of)


__all__ = [
    "COMPLETENESS_FORMULA",
    "DOC_KEY_TO_DOC_KIND",
    "DOC_KIND_TO_DOC_KEYS",
    "DataRoomStore",
    "ITEM_STATUSES",
    "PHASE_WEIGHTS",
    "STATUS_CREDITS",
    "completeness_index",
]
