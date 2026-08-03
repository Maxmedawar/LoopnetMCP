"""Persistence for ingested documents and their extracted claims.

Mirrors ``DealStore``: an async façade over the shared cache SQLite DB. Document
blobs are content-addressed on disk (sha256) so re-ingesting the same OM dedupes
automatically; claims and document metadata live in SQLite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cre_mcp.config import CreConfig
from cre_mcp.source_rights.output import safe_error_message, safe_source_reference
from cre_mcp.truth.models import DocumentRecord, FieldClaim

logger = logging.getLogger(__name__)


class TruthStore:
    """Async façade over durable truth tables + a content-addressed blob store."""

    def __init__(self, config: CreConfig | None = None) -> None:
        self._config = config or CreConfig()
        resolved = self._config.cache_db_path
        self.db_path = Path(resolved).expanduser()
        self.blob_dir = self.db_path.parent / "documents"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS truth_documents (
                document_id TEXT NOT NULL,
                deal_id TEXT NOT NULL,
                doc_kind TEXT NOT NULL,
                source_channel TEXT NOT NULL,
                origin TEXT,
                blob_path TEXT NOT NULL,
                n_pages INTEGER,
                parse_status TEXT NOT NULL,
                redactions INTEGER NOT NULL DEFAULT 0,
                ingested_at TEXT NOT NULL,
                PRIMARY KEY(deal_id, document_id)
            );
            CREATE INDEX IF NOT EXISTS idx_truth_docs_deal
                ON truth_documents(deal_id, ingested_at);

            CREATE TABLE IF NOT EXISTS truth_claims (
                deal_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                field TEXT NOT NULL,
                subject TEXT NOT NULL DEFAULT '',
                claim_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                PRIMARY KEY(deal_id, document_id, field, subject)
            );
            CREATE INDEX IF NOT EXISTS idx_truth_claims_deal
                ON truth_claims(deal_id, field);
            """
        )
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _blob_path_for(self, sha256: str, ext: str) -> Path:
        return self.blob_dir / f"{sha256}.{ext}"

    def _save_document(
        self, record: DocumentRecord, blob: bytes, claims: list[FieldClaim], ext: str
    ) -> DocumentRecord:
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = self._blob_path_for(record.document_id, ext)
        if not blob_path.exists():
            blob_path.write_bytes(blob)
        record = record.model_copy(update={"blob_path": str(blob_path)})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO truth_documents(
                    document_id, deal_id, doc_kind, source_channel, origin,
                    blob_path, n_pages, parse_status, redactions, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id, document_id) DO UPDATE SET
                    doc_kind = excluded.doc_kind,
                    origin = excluded.origin,
                    n_pages = excluded.n_pages,
                    parse_status = excluded.parse_status,
                    redactions = excluded.redactions,
                    ingested_at = excluded.ingested_at
                """,
                (
                    record.document_id, record.deal_id, record.doc_kind.value,
                    record.source_channel, record.origin, record.blob_path,
                    record.n_pages, record.parse_status, record.redactions, record.ingested_at,
                ),
            )
            connection.execute(
                "DELETE FROM truth_claims WHERE deal_id = ? AND document_id = ?",
                (record.deal_id, record.document_id),
            )
            for claim in claims:
                connection.execute(
                    """
                    INSERT INTO truth_claims(
                        deal_id, document_id, field, subject, claim_json, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deal_id, document_id, field, subject) DO UPDATE SET
                        claim_json = excluded.claim_json,
                        confidence = excluded.confidence
                    """,
                    (
                        record.deal_id, record.document_id, claim.field,
                        claim.subject or "", claim.model_dump_json(), claim.figure.confidence,
                    ),
                )
        return record

    async def save_document(
        self, record: DocumentRecord, blob: bytes, claims: list[FieldClaim], *, ext: str
    ) -> DocumentRecord | None:
        """Persist a document blob + metadata + its extracted claims."""
        try:
            return await asyncio.to_thread(self._save_document, record, blob, claims, ext)
        except Exception as exc:
            logger.error(
                "truth document save failed for %s: %s",
                safe_source_reference(record.deal_id, config=self._config),
                safe_error_message(exc, config=self._config),
            )
            return None

    def _list_documents(self, deal_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.document_id, d.doc_kind, d.source_channel, d.origin,
                       d.n_pages, d.parse_status, d.redactions, d.ingested_at,
                       COUNT(c.field) AS claim_count
                FROM truth_documents d
                LEFT JOIN truth_claims c
                    ON c.deal_id = d.deal_id AND c.document_id = d.document_id
                WHERE d.deal_id = ?
                GROUP BY d.document_id
                ORDER BY d.ingested_at DESC, d.document_id
                """,
                (deal_id,),
            ).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "doc_kind": row["doc_kind"],
                "source_channel": row["source_channel"],
                "origin": row["origin"],
                "n_pages": row["n_pages"],
                "parse_status": row["parse_status"],
                "redactions": row["redactions"],
                "ingested_at": row["ingested_at"],
                "claim_count": int(row["claim_count"] or 0),
            }
            for row in rows
        ]

    async def list_documents(self, deal_id: str) -> list[dict]:
        """Return ingested documents for a deal with per-document claim counts."""
        try:
            return await asyncio.to_thread(self._list_documents, deal_id)
        except Exception as exc:
            logger.error(
                "truth document list failed for %s: %s",
                safe_source_reference(deal_id, config=self._config),
                safe_error_message(exc, config=self._config),
            )
            return []

    def _get_claims(self, deal_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT claim_json FROM truth_claims WHERE deal_id = ? ORDER BY field, subject",
                (deal_id,),
            ).fetchall()
        return [json.loads(str(row["claim_json"])) for row in rows]

    async def get_claims(self, deal_id: str) -> list[dict]:
        """Return every stored claim for a deal (consumed by reconciliation in Phase 26)."""
        try:
            return await asyncio.to_thread(self._get_claims, deal_id)
        except Exception as exc:
            logger.error(
                "truth claim read failed for %s: %s",
                safe_source_reference(deal_id, config=self._config),
                safe_error_message(exc, config=self._config),
            )
            return []


def get_truth_store(config: CreConfig | None = None) -> TruthStore:
    """Build a TruthStore over the configured shared database."""
    return TruthStore(config=config or CreConfig())


__all__ = ["TruthStore", "get_truth_store"]
