"""Request-scoped PostgreSQL persistence for document truth assets."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.truth.models import DocumentRecord, FieldClaim

_UNAVAILABLE = "truth-asset persistence unavailable"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORMATS = frozenset({"pdf", "xlsx", "csv"})
_MAX_BLOB_BYTES = 50 * 1024 * 1024
_MAX_CLAIMS = 10_000


class TruthAssetUnavailable(RuntimeError):
    """The exact hosted truth-asset boundary cannot complete safely."""


async def _finish_thread_before_cancellation(function: Any, *args: Any) -> Any:
    """Keep a worker inside its request lease before cancellation escapes."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        try:
            task.result()
        except Exception:
            pass
        raise


def _text(
    value: object,
    *,
    maximum: int,
    nullable: bool = False,
    blank: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or "\x00" in value or len(value) > maximum:
        raise ValueError("invalid truth-asset text")
    if not blank and (not value or value != value.strip()):
        raise ValueError("invalid truth-asset text")
    return value


def _utc_datetime(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("invalid truth-asset timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid truth-asset timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("invalid truth-asset timestamp")
    return parsed.astimezone(UTC)


def _utc_text(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("invalid stored truth-asset timestamp")
    return value.astimezone(UTC).isoformat()


def _digest_hex(value: object) -> str:
    digest = bytes(value)  # type: ignore[arg-type]
    if len(digest) != 32:
        raise ValueError("invalid stored truth-asset digest")
    return digest.hex()


def _validate_origin(origin: str | None, source_channel: str) -> str | None:
    selected = _text(origin, maximum=4096, nullable=True, blank=True)
    if selected is None:
        return None
    if source_channel != "scraped":
        return selected
    try:
        parsed = urlsplit(selected)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid truth-asset origin") from error
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid truth-asset origin")
    normalized_host = host.casefold().rstrip(".")
    netloc = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    if port is not None and port != 443:
        netloc = f"{netloc}:{port}"
    if selected != f"https://{netloc}{parsed.path}":
        raise ValueError("invalid truth-asset origin")
    return selected


class PostgresTruthAssetRepository:
    """Persist and read one workspace's document truth through an admission."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("truth-asset repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self) -> TenantContext:
        repositories = current_hosted_request_repositories()
        context = current_context()
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("truth_asset") is not self
            or not isinstance(context, TenantContext)
            or context.trusted
            or not context.active
        ):
            raise TruthAssetUnavailable(_UNAVAILABLE)
        comparisons = (
            (context.workspace_id, self._admission.workspace_public_id),
            (context.actor_id, self._admission.actor_user_id),
            (context.session_id, self._admission.session_id),
        )
        if any(
            not left
            or not right
            or not hmac.compare_digest(left, right)
            for left, right in comparisons
        ):
            raise TruthAssetUnavailable(_UNAVAILABLE)
        return context

    @staticmethod
    def _validate_asset(
        record: DocumentRecord,
        blob: bytes,
        claims: list[FieldClaim],
        ext: str,
    ) -> tuple[DocumentRecord, bytes, list[FieldClaim], str, datetime]:
        if not isinstance(record, DocumentRecord):
            raise ValueError("invalid truth-asset document")
        normalized_record = DocumentRecord.model_validate(
            record.model_dump(mode="python")
        )
        if not isinstance(blob, bytes) or not 1 <= len(blob) <= _MAX_BLOB_BYTES:
            raise ValueError("invalid truth-asset blob")
        if (
            not isinstance(ext, str)
            or ext not in _FORMATS
            or ext != ext.strip().casefold()
        ):
            raise ValueError("invalid truth-asset format")
        if normalized_record.blob_path != "":
            raise ValueError("hosted truth assets cannot contain local paths")
        document_id = normalized_record.document_id
        actual_digest = hashlib.sha256(blob).hexdigest()
        if (
            _DIGEST.fullmatch(document_id) is None
            or not hmac.compare_digest(document_id, actual_digest)
        ):
            raise ValueError("invalid truth-asset digest")
        _text(normalized_record.deal_id, maximum=512)
        origin = _validate_origin(
            normalized_record.origin,
            normalized_record.source_channel,
        )
        if origin != normalized_record.origin:
            raise ValueError("invalid truth-asset origin")
        if (
            normalized_record.n_pages is not None
            and (
                isinstance(normalized_record.n_pages, bool)
                or not 1 <= normalized_record.n_pages <= 1_000_000
            )
        ):
            raise ValueError("invalid truth-asset page count")
        if (
            isinstance(normalized_record.redactions, bool)
            or not 0 <= normalized_record.redactions <= 1_000_000
        ):
            raise ValueError("invalid truth-asset redaction count")
        ingested_at = _utc_datetime(normalized_record.ingested_at)
        if not isinstance(claims, list) or len(claims) > _MAX_CLAIMS:
            raise ValueError("invalid truth-asset claims")

        normalized_claims: list[FieldClaim] = []
        seen: set[tuple[str, str]] = set()
        for candidate in claims:
            if not isinstance(candidate, FieldClaim):
                raise ValueError("invalid truth-asset claim")
            claim = FieldClaim.model_validate(candidate.model_dump(mode="python"))
            field = _text(claim.field, maximum=128)
            subject = _text(
                claim.subject,
                maximum=512,
                nullable=True,
            )
            key = (field or "", subject or "")
            if key in seen:
                raise ValueError("duplicate truth-asset claim")
            seen.add(key)
            figure = claim.figure
            lineage = figure.lineage
            if (
                lineage.document_id != document_id
                or lineage.doc_kind != normalized_record.doc_kind
                or lineage.source_channel != normalized_record.source_channel
                or lineage.origin != normalized_record.origin
            ):
                raise ValueError("truth-asset lineage mismatch")
            if isinstance(figure.value, float):
                if not math.isfinite(figure.value):
                    raise ValueError("invalid truth-asset number")
            elif isinstance(figure.value, str):
                _text(figure.value, maximum=16384, blank=True)
            elif figure.value is not None:
                raise ValueError("invalid truth-asset value")
            if not math.isfinite(figure.confidence):
                raise ValueError("invalid truth-asset confidence")
            if (
                lineage.page is not None
                and (
                    isinstance(lineage.page, bool)
                    or not 1 <= lineage.page <= 1_000_000
                )
            ):
                raise ValueError("invalid truth-asset lineage page")
            _text(lineage.cell, maximum=256, nullable=True, blank=True)
            _text(lineage.raw_text, maximum=8192, blank=True)
            _validate_origin(lineage.origin, lineage.source_channel)
            if lineage.bbox is not None and (
                len(lineage.bbox) != 4
                or any(not math.isfinite(value) for value in lineage.bbox)
            ):
                raise ValueError("invalid truth-asset lineage box")
            if len(claim.flags) > 32 or len(set(claim.flags)) != len(claim.flags):
                raise ValueError("invalid truth-asset flags")
            total_flag_length = 0
            for flag in claim.flags:
                selected_flag = _text(flag, maximum=128)
                total_flag_length += len(selected_flag or "")
            if total_flag_length > 4096:
                raise ValueError("invalid truth-asset flags")
            normalized_claims.append(claim)
        return normalized_record, blob, normalized_claims, ext, ingested_at

    @staticmethod
    def _value_columns(value: float | str | None) -> tuple[str, float | None, str | None]:
        if value is None:
            return "null", None, None
        if isinstance(value, float):
            return "number", value, None
        return "text", None, value

    def _save_document(
        self,
        record: DocumentRecord,
        blob: bytes,
        claims: list[FieldClaim],
        ext: str,
    ) -> DocumentRecord:
        self._require_active_scope()
        record, blob, claims, ext, ingested_at = self._validate_asset(
            record,
            blob,
            claims,
            ext,
        )
        with self._database.admitted_connection(self._admission) as connection:
            connection.execute(
                "INSERT INTO medawarcre.truth_document_blobs("
                "workspace_id,document_id,content) VALUES ("
                "medawarcre.current_workspace_id(),decode(%s,'hex'),%s) "
                "ON CONFLICT (workspace_id,document_id) DO NOTHING",
                (record.document_id, blob),
            )
            connection.execute(
                "INSERT INTO medawarcre.truth_documents("
                "workspace_id,deal_ref,document_id,doc_kind,source_channel,origin,"
                "format,n_pages,parse_status,redactions,ingested_at) VALUES ("
                "medawarcre.current_workspace_id(),%s,decode(%s,'hex'),%s,%s,%s,"
                "%s,%s,%s,%s,%s) "
                "ON CONFLICT (workspace_id,deal_ref,document_id) DO UPDATE SET "
                "doc_kind=excluded.doc_kind,source_channel=excluded.source_channel,"
                "origin=excluded.origin,format=excluded.format,n_pages=excluded.n_pages,"
                "parse_status=excluded.parse_status,"
                "redactions=excluded.redactions,ingested_at=excluded.ingested_at",
                (
                    record.deal_id,
                    record.document_id,
                    record.doc_kind.value,
                    record.source_channel,
                    record.origin,
                    ext,
                    record.n_pages,
                    record.parse_status,
                    record.redactions,
                    ingested_at,
                ),
            )
            connection.execute(
                "DELETE FROM medawarcre.truth_claims WHERE "
                "workspace_id=medawarcre.current_workspace_id() "
                "AND deal_ref=%s AND document_id=decode(%s,'hex')",
                (record.deal_id, record.document_id),
            )
            for claim in claims:
                figure = claim.figure
                lineage = figure.lineage
                value_kind, value_number, value_text = self._value_columns(
                    figure.value
                )
                connection.execute(
                    "INSERT INTO medawarcre.truth_claims("
                    "workspace_id,deal_ref,document_id,field,subject,value_kind,"
                    "value_number,value_text,unit,confidence,lineage_doc_kind,"
                    "lineage_source_channel,lineage_page,lineage_cell,lineage_bbox,"
                    "lineage_raw_text,extraction_method,lineage_origin,flags) VALUES ("
                    "medawarcre.current_workspace_id(),%s,decode(%s,'hex'),%s,%s,%s,"
                    "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        record.deal_id,
                        record.document_id,
                        claim.field,
                        claim.subject or "",
                        value_kind,
                        value_number,
                        value_text,
                        figure.unit,
                        figure.confidence,
                        lineage.doc_kind.value,
                        lineage.source_channel,
                        lineage.page,
                        lineage.cell,
                        None if lineage.bbox is None else list(lineage.bbox),
                        lineage.raw_text,
                        lineage.extraction_method.value,
                        lineage.origin,
                        list(claim.flags),
                    ),
                )
        return record

    async def save_document(
        self,
        record: DocumentRecord,
        blob: bytes,
        claims: list[FieldClaim],
        *,
        ext: str,
    ) -> DocumentRecord:
        """Atomically store one content-addressed document and its claims."""
        try:
            return await _finish_thread_before_cancellation(
                self._save_document,
                record,
                blob,
                claims,
                ext,
            )
        except TruthAssetUnavailable:
            raise
        except Exception as error:
            raise TruthAssetUnavailable(_UNAVAILABLE) from error

    def _list_documents(self, deal_id: str) -> list[dict[str, Any]]:
        self._require_active_scope()
        selected_deal = _text(deal_id, maximum=512)
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT document.document_id,document.doc_kind,"
                "document.source_channel,document.origin,document.n_pages,"
                "document.parse_status,document.redactions,document.ingested_at,"
                "count(claim.field) FROM medawarcre.truth_documents document "
                "LEFT JOIN medawarcre.truth_claims claim ON "
                "claim.workspace_id=document.workspace_id "
                "AND claim.deal_ref=document.deal_ref "
                "AND claim.document_id=document.document_id "
                "WHERE document.workspace_id=medawarcre.current_workspace_id() "
                "AND document.deal_ref=%s "
                "GROUP BY document.workspace_id,document.deal_ref,document.document_id "
                "ORDER BY document.ingested_at DESC,document.document_id",
                (selected_deal,),
            ).fetchall()
        return [
            {
                "document_id": _digest_hex(row[0]),
                "doc_kind": str(row[1]),
                "source_channel": str(row[2]),
                "origin": None if row[3] is None else str(row[3]),
                "n_pages": None if row[4] is None else int(row[4]),
                "parse_status": str(row[5]),
                "redactions": int(row[6]),
                "ingested_at": _utc_text(row[7]),
                "claim_count": int(row[8]),
            }
            for row in rows
        ]

    async def list_documents(self, deal_id: str) -> list[dict[str, Any]]:
        """Return one workspace's document metadata without raw blob content."""
        try:
            return await _finish_thread_before_cancellation(
                self._list_documents,
                deal_id,
            )
        except TruthAssetUnavailable:
            raise
        except Exception as error:
            raise TruthAssetUnavailable(_UNAVAILABLE) from error

    def _get_claims(self, deal_id: str) -> list[dict[str, Any]]:
        self._require_active_scope()
        selected_deal = _text(deal_id, maximum=512)
        with self._database.admitted_connection(self._admission) as connection:
            rows = connection.execute(
                "SELECT document_id,field,subject,value_kind,value_number,value_text,"
                "unit,confidence,lineage_doc_kind,lineage_source_channel,"
                "lineage_page,lineage_cell,lineage_bbox,lineage_raw_text,"
                "extraction_method,lineage_origin,flags "
                "FROM medawarcre.truth_claims WHERE "
                "workspace_id=medawarcre.current_workspace_id() AND deal_ref=%s "
                "ORDER BY field,subject,document_id",
                (selected_deal,),
            ).fetchall()
        claims: list[dict[str, Any]] = []
        for row in rows:
            value_kind = str(row[3])
            if value_kind == "null":
                value: float | str | None = None
            elif value_kind == "number":
                value = float(row[4])
                if not math.isfinite(value):
                    raise ValueError("invalid stored truth-asset number")
            elif value_kind == "text":
                value = str(row[5])
            else:
                raise ValueError("invalid stored truth-asset value")
            bbox = (
                None
                if row[12] is None
                else tuple(float(item) for item in row[12])
            )
            if bbox is not None and (
                len(bbox) != 4 or any(not math.isfinite(item) for item in bbox)
            ):
                raise ValueError("invalid stored truth-asset lineage box")
            claim = FieldClaim.model_validate(
                {
                    "field": str(row[1]),
                    "subject": None if str(row[2]) == "" else str(row[2]),
                    "figure": {
                        "value": value,
                        "unit": str(row[6]),
                        "confidence": float(row[7]),
                        "lineage": {
                            "document_id": _digest_hex(row[0]),
                            "doc_kind": str(row[8]),
                            "source_channel": str(row[9]),
                            "page": None if row[10] is None else int(row[10]),
                            "cell": None if row[11] is None else str(row[11]),
                            "bbox": bbox,
                            "raw_text": str(row[13]),
                            "extraction_method": str(row[14]),
                            "origin": None if row[15] is None else str(row[15]),
                        },
                    },
                    "flags": [str(item) for item in row[16]],
                }
            )
            claims.append(claim.model_dump(mode="json"))
        return claims

    async def get_claims(self, deal_id: str) -> list[dict[str, Any]]:
        """Return native structured claims for one admitted workspace."""
        try:
            return await _finish_thread_before_cancellation(
                self._get_claims,
                deal_id,
            )
        except TruthAssetUnavailable:
            raise
        except Exception as error:
            raise TruthAssetUnavailable(_UNAVAILABLE) from error


__all__ = ["PostgresTruthAssetRepository", "TruthAssetUnavailable"]
