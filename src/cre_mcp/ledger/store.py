"""Append-only ledger tables on the shared cache database.

Same SQLite file as :class:`cre_mcp.deals.store.DealStore`, own connection —
the ledgers never mutate deal state, they only accumulate evidence.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cre_mcp.config import CreConfig
from cre_mcp.ledger.models import (
    ClaimOutcomeRecord,
    DefectRecord,
    QuoteRecord,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claim_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id TEXT NOT NULL,
    field TEXT NOT NULL,
    subject TEXT,
    counterparty TEXT,
    counterparty_role TEXT NOT NULL DEFAULT 'unknown',
    claimed_value TEXT,
    claimed_doc_kind TEXT NOT NULL,
    proven_value TEXT,
    proven_doc_kind TEXT,
    verdict TEXT NOT NULL,
    delta_pct REAL,
    severity TEXT,
    source_document_id TEXT,
    recorded_at TEXT NOT NULL
);
-- NULL-safe identity: SQLite treats NULLs as distinct inside UNIQUE constraints,
-- so idempotency needs COALESCE'd expressions in a unique index instead.
CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_ledger_identity ON claim_ledger(
    deal_id, field, COALESCE(subject, ''), claimed_doc_kind,
    COALESCE(source_document_id, '')
);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_counterparty ON claim_ledger(counterparty);
CREATE INDEX IF NOT EXISTS idx_claim_ledger_deal ON claim_ledger(deal_id);

CREATE TABLE IF NOT EXISTS quote_ledger (
    quote_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    lender TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'quoted',
    rate_pct REAL,
    proceeds REAL,
    ltv_pct REAL,
    io_months INTEGER,
    amort_years INTEGER,
    recourse TEXT,
    prepay TEXT,
    notes TEXT,
    final_rate_pct REAL,
    final_proceeds REAL,
    final_recourse TEXT,
    retrade_rate_bps REAL,
    retrade_proceeds_pct REAL,
    days_quote_to_close INTEGER,
    quoted_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_quote_ledger_lender ON quote_ledger(lender);

CREATE TABLE IF NOT EXISTS defect_ledger (
    defect_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL,
    defect_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    discovered_stage TEXT NOT NULL,
    discovered_by TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'open',
    outcome_notes TEXT,
    dollar_impact REAL,
    flagged_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_defect_ledger_deal ON defect_ledger(deal_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _encode(value: float | str | None) -> str | None:
    return None if value is None else str(value)


def _decode(raw: str | None) -> float | str | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return raw


class LedgerStore:
    """Async façade over the append-only evidence ledgers."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or CreConfig().cache_db_path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(_SCHEMA)
        return connection

    # ------------------------------------------------------------- claims
    async def record_claims(self, records: list[ClaimOutcomeRecord]) -> int:
        """Insert claim outcomes, silently skipping exact duplicates.

        Duplicate skipping makes repeated ``reconcile_deal_docs`` runs idempotent:
        the same (deal, field, subject, doc kind, document) never double-counts.
        """

        def _write() -> int:
            written = 0
            with self._connect() as conn:
                for rec in records:
                    try:
                        conn.execute(
                            """INSERT INTO claim_ledger
                               (deal_id, field, subject, counterparty, counterparty_role,
                                claimed_value, claimed_doc_kind, proven_value, proven_doc_kind,
                                verdict, delta_pct, severity, source_document_id, recorded_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                rec.deal_id, rec.field, rec.subject, rec.counterparty,
                                rec.counterparty_role, _encode(rec.claimed_value),
                                rec.claimed_doc_kind, _encode(rec.proven_value),
                                rec.proven_doc_kind, rec.verdict, rec.delta_pct,
                                rec.severity, rec.source_document_id, rec.recorded_at,
                            ),
                        )
                        written += 1
                    except sqlite3.IntegrityError:
                        continue  # already recorded — append-only, never overwrite
            return written

        return await asyncio.to_thread(_write)

    async def claims_for(
        self, *, counterparty: str | None = None, deal_id: str | None = None
    ) -> list[ClaimOutcomeRecord]:
        def _read() -> list[ClaimOutcomeRecord]:
            clauses, params = [], []
            if counterparty is not None:
                clauses.append("counterparty = ?")
                params.append(counterparty)
            if deal_id is not None:
                clauses.append("deal_id = ?")
                params.append(deal_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM claim_ledger {where} ORDER BY recorded_at", params
                ).fetchall()
            return [
                ClaimOutcomeRecord(
                    deal_id=r["deal_id"], field=r["field"], subject=r["subject"],
                    counterparty=r["counterparty"], counterparty_role=r["counterparty_role"],
                    claimed_value=_decode(r["claimed_value"]),
                    claimed_doc_kind=r["claimed_doc_kind"],
                    proven_value=_decode(r["proven_value"]),
                    proven_doc_kind=r["proven_doc_kind"], verdict=r["verdict"],
                    delta_pct=r["delta_pct"], severity=r["severity"],
                    source_document_id=r["source_document_id"], recorded_at=r["recorded_at"],
                )
                for r in rows
            ]

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------- quotes
    async def record_quote(self, rec: QuoteRecord) -> str:
        def _write() -> str:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO quote_ledger
                       (quote_id, deal_id, lender, stage, rate_pct, proceeds, ltv_pct,
                        io_months, amort_years, recourse, prepay, notes, quoted_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rec.quote_id, rec.deal_id, rec.lender, rec.stage, rec.rate_pct,
                        rec.proceeds, rec.ltv_pct, rec.io_months, rec.amort_years,
                        rec.recourse, rec.prepay, rec.notes, rec.quoted_at,
                    ),
                )
            return rec.quote_id

        return await asyncio.to_thread(_write)

    async def resolve_quote(
        self,
        quote_id: str,
        *,
        stage: str,
        final_rate_pct: float | None = None,
        final_proceeds: float | None = None,
        final_recourse: str | None = None,
    ) -> QuoteRecord | None:
        """Record how a quote ended and compute the retrade deltas from stored terms."""

        def _write() -> QuoteRecord | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM quote_ledger WHERE quote_id = ?", (quote_id,)
                ).fetchone()
                if row is None:
                    return None
                retrade_bps = (
                    round((final_rate_pct - row["rate_pct"]) * 100, 2)
                    if final_rate_pct is not None and row["rate_pct"] is not None
                    else None
                )
                retrade_proceeds = (
                    round((final_proceeds - row["proceeds"]) / row["proceeds"], 6)
                    if final_proceeds is not None and row["proceeds"]
                    else None
                )
                resolved_at = _now()
                days = None
                try:
                    quoted = datetime.fromisoformat(row["quoted_at"])
                    days = (datetime.fromisoformat(resolved_at) - quoted).days
                except ValueError:
                    pass
                conn.execute(
                    """UPDATE quote_ledger SET stage=?, final_rate_pct=?, final_proceeds=?,
                       final_recourse=?, retrade_rate_bps=?, retrade_proceeds_pct=?,
                       days_quote_to_close=?, resolved_at=? WHERE quote_id=?""",
                    (
                        stage, final_rate_pct, final_proceeds, final_recourse,
                        retrade_bps, retrade_proceeds, days, resolved_at, quote_id,
                    ),
                )
                fresh = conn.execute(
                    "SELECT * FROM quote_ledger WHERE quote_id = ?", (quote_id,)
                ).fetchone()
            return _quote_from_row(fresh)

        return await asyncio.to_thread(_write)

    async def quotes_for(self, *, lender: str | None = None) -> list[QuoteRecord]:
        def _read() -> list[QuoteRecord]:
            where, params = ("WHERE lender = ?", [lender]) if lender else ("", [])
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM quote_ledger {where} ORDER BY quoted_at", params
                ).fetchall()
            return [_quote_from_row(r) for r in rows]

        return await asyncio.to_thread(_read)

    # ------------------------------------------------------------ defects
    async def record_defect(self, rec: DefectRecord) -> str:
        def _write() -> str:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO defect_ledger
                       (defect_id, deal_id, defect_type, description, severity,
                        discovered_stage, discovered_by, outcome, outcome_notes,
                        dollar_impact, flagged_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rec.defect_id, rec.deal_id, rec.defect_type, rec.description,
                        rec.severity, rec.discovered_stage, rec.discovered_by,
                        rec.outcome, rec.outcome_notes, rec.dollar_impact, rec.flagged_at,
                    ),
                )
            return rec.defect_id

        return await asyncio.to_thread(_write)

    async def resolve_defect(
        self,
        defect_id: str,
        *,
        outcome: str,
        outcome_notes: str | None = None,
        dollar_impact: float | None = None,
    ) -> DefectRecord | None:
        def _write() -> DefectRecord | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM defect_ledger WHERE defect_id = ?", (defect_id,)
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    """UPDATE defect_ledger SET outcome=?, outcome_notes=?,
                       dollar_impact=?, resolved_at=? WHERE defect_id=?""",
                    (outcome, outcome_notes, dollar_impact, _now(), defect_id),
                )
                fresh = conn.execute(
                    "SELECT * FROM defect_ledger WHERE defect_id = ?", (defect_id,)
                ).fetchone()
            return _defect_from_row(fresh)

        return await asyncio.to_thread(_write)

    async def defects_for(self, deal_id: str | None = None) -> list[DefectRecord]:
        def _read() -> list[DefectRecord]:
            where, params = ("WHERE deal_id = ?", [deal_id]) if deal_id else ("", [])
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM defect_ledger {where} ORDER BY flagged_at", params
                ).fetchall()
            return [_defect_from_row(r) for r in rows]

        return await asyncio.to_thread(_read)


def _quote_from_row(r: sqlite3.Row) -> QuoteRecord:
    return QuoteRecord(
        quote_id=r["quote_id"], deal_id=r["deal_id"], lender=r["lender"], stage=r["stage"],
        rate_pct=r["rate_pct"], proceeds=r["proceeds"], ltv_pct=r["ltv_pct"],
        io_months=r["io_months"], amort_years=r["amort_years"], recourse=r["recourse"],
        prepay=r["prepay"], notes=r["notes"], final_rate_pct=r["final_rate_pct"],
        final_proceeds=r["final_proceeds"], final_recourse=r["final_recourse"],
        retrade_rate_bps=r["retrade_rate_bps"], retrade_proceeds_pct=r["retrade_proceeds_pct"],
        days_quote_to_close=r["days_quote_to_close"], quoted_at=r["quoted_at"],
        resolved_at=r["resolved_at"],
    )


def _defect_from_row(r: sqlite3.Row) -> DefectRecord:
    return DefectRecord(
        defect_id=r["defect_id"], deal_id=r["deal_id"], defect_type=r["defect_type"],
        description=r["description"], severity=r["severity"],
        discovered_stage=r["discovered_stage"], discovered_by=r["discovered_by"],
        outcome=r["outcome"], outcome_notes=r["outcome_notes"],
        dollar_impact=r["dollar_impact"], flagged_at=r["flagged_at"],
        resolved_at=r["resolved_at"],
    )


def new_id(prefix: str) -> str:
    """Short, prefixed, collision-safe id for quotes/defects."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_STORE: LedgerStore | None = None


def get_ledger_store() -> LedgerStore:
    global _STORE
    if _STORE is None:
        _STORE = LedgerStore()
    return _STORE


def reset_ledger_store() -> None:
    """Test hook: drop the cached singleton."""
    global _STORE
    _STORE = None
