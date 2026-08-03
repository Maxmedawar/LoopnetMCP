"""Server-owned rights attestations for externally hosted deal documents."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from cre_mcp.access.context import (
    TenantContext,
    current_context,
    current_runtime_config,
)
from cre_mcp.config import CreConfig
from cre_mcp.source_rights.gate import (
    SourceRightsDeniedError,
    is_hosted_execution,
    require_source,
)
from cre_mcp.source_rights.registry import get_rights_registry

DOCUMENT_PURPOSES = frozenset({"retrieve", "store", "derive", "output"})


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def normalized_document_url(url: str) -> str:
    """Return the exact request identity used only as input to a one-way digest."""
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("external document URL must be absolute HTTP(S)")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("external document URL has an invalid port") from exc
    # Keep netloc bytes (including userinfo), path, query ordering, and signed
    # query values exact. Only the fragment is omitted because it is not sent in
    # an HTTP request. The returned value is never persisted or logged.
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def document_url_hash(url: str) -> str:
    return hashlib.sha256(normalized_document_url(url).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentRightsAttestation:
    attestation_id: str
    workspace_id: str
    actor_id: str
    session_id: str
    url_hash: str
    evidence_url: str
    evidence_hash: str
    allowed_purposes: tuple[str, ...]
    approved_by: str
    approved_at: str
    expires_at: str


class DocumentAttestationRepository(Protocol):
    def require(
        self,
        *,
        attestation_id: str,
        context: TenantContext,
        url: str,
        purposes: Iterable[str],
    ) -> DocumentRightsAttestation: ...


_hosted_repository: ContextVar[DocumentAttestationRepository | None] = ContextVar(
    "source_document_attestation_repository",
    default=None,
)


@contextmanager
def use_hosted_document_attestation_repository(
    repository: DocumentAttestationRepository | None,
):
    """Inject the server's durable hosted repository for one request scope."""
    token = _hosted_repository.set(repository)
    try:
        yield repository
    finally:
        _hosted_repository.reset(token)


_ADMIN_AUTHORITY_MARKER = object()


@dataclass(frozen=True)
class DocumentAdminAuthority:
    actor_id: str
    session_id: str
    role: str
    _marker: object


def issue_document_admin_authority(outcome: Any) -> DocumentAdminAuthority:
    """Mint a short-lived capability only from a live platform admin outcome."""
    from cre_mcp.platform.auth import AuthenticatedSession
    from cre_mcp.platform.authority import AuthorityOutcome, InternalAdminAuthority

    internal_admin = getattr(outcome, "internal_admin", None)
    session = getattr(outcome, "session", None)
    expires = getattr(session, "access_expires_at", None)
    if (
        not isinstance(outcome, AuthorityOutcome)
        or not isinstance(internal_admin, InternalAdminAuthority)
        or not isinstance(session, AuthenticatedSession)
        or not isinstance(expires, datetime)
        or expires.tzinfo is None
        or expires <= _now()
        or internal_admin.user_id != session.user_id
        or internal_admin.role not in {"platform_admin", "support"}
        or not session.session_id.strip()
    ):
        raise SourceRightsDeniedError(
            "source-rights denied: live server admin authority is required"
        )
    return DocumentAdminAuthority(
        actor_id=str(internal_admin.user_id),
        session_id=str(session.session_id),
        role=str(internal_admin.role),
        _marker=_ADMIN_AUTHORITY_MARKER,
    )


def _require_admin(
    authority: DocumentAdminAuthority | None,
) -> DocumentAdminAuthority:
    if (
        authority is None
        or authority._marker is not _ADMIN_AUTHORITY_MARKER
        or not authority.actor_id.strip()
        or not authority.session_id.strip()
    ):
        raise SourceRightsDeniedError(
            "source-rights denied: live server admin authority is required"
        )
    return authority


def _require_trusted_local() -> None:
    context = current_context()
    if context is None or not context.trusted:
        raise SourceRightsDeniedError(
            "source-rights denied: SQLite attestation authority is trusted-local only"
        )


class DocumentAttestationStore:
    """SQLite-backed approvals that never persist the attested external URL."""

    def __init__(self, db_path: str | Path) -> None:
        _require_trusted_local()
        self.db_path = Path(db_path).expanduser()
        self._memory_connection: sqlite3.Connection | None = None
        if str(self.db_path) == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:")
            self._memory_connection.row_factory = sqlite3.Row
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._memory_connection
        owns_connection = connection is None
        if connection is None:
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            if owns_connection:
                connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_document_attestations (
                    attestation_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    url_hash TEXT NOT NULL,
                    evidence_url TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    allowed_purposes TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_source_document_attestation_scope
                ON source_document_attestations (
                    workspace_id, actor_id, session_id, url_hash
                )
                """
            )
        if str(self.db_path) != ":memory:":
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass

    def approve(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        session_id: str,
        url: str,
        evidence_url: str,
        evidence_hash: str,
        allowed_purposes: Iterable[str],
        expires_at: datetime,
        admin_authority: DocumentAdminAuthority | None,
        approved_at: datetime | None = None,
    ) -> DocumentRightsAttestation:
        _require_trusted_local()
        authority = _require_admin(admin_authority)
        scope = {
            "workspace_id": workspace_id.strip(),
            "actor_id": actor_id.strip(),
            "session_id": session_id.strip(),
            "approved_by": authority.actor_id,
        }
        if any(not value for value in scope.values()):
            raise ValueError("attestation scope and approver cannot be blank")
        parsed_evidence = urlsplit(evidence_url.strip())
        if (
            parsed_evidence.scheme != "https"
            or not parsed_evidence.hostname
            or parsed_evidence.username is not None
            or parsed_evidence.password is not None
        ):
            raise ValueError(
                "attestation evidence_url must be credential-free absolute HTTPS"
            )
        normalized_hash = evidence_hash.strip().casefold()
        if len(normalized_hash) != 64 or any(
            char not in "0123456789abcdef" for char in normalized_hash
        ):
            raise ValueError("attestation evidence_hash must be SHA-256 hex")
        purposes = tuple(
            sorted({str(item).strip().casefold() for item in allowed_purposes})
        )
        if not purposes or not set(purposes).issubset(DOCUMENT_PURPOSES):
            raise ValueError("attestation has an unknown or empty allowed purpose")
        approved = approved_at or _now()
        if approved.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("attestation timestamps must be timezone-aware")
        if expires_at <= approved:
            raise ValueError("attestation expiry must follow approval")

        record = DocumentRightsAttestation(
            attestation_id=f"srcatt_{uuid.uuid4().hex}",
            workspace_id=scope["workspace_id"],
            actor_id=scope["actor_id"],
            session_id=scope["session_id"],
            url_hash=document_url_hash(url),
            evidence_url=evidence_url.strip(),
            evidence_hash=normalized_hash,
            allowed_purposes=purposes,
            approved_by=scope["approved_by"],
            approved_at=approved.astimezone(UTC).isoformat(),
            expires_at=expires_at.astimezone(UTC).isoformat(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_document_attestations (
                    attestation_id, workspace_id, actor_id, session_id, url_hash,
                    evidence_url, evidence_hash, allowed_purposes, approved_by,
                    approved_at, expires_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    record.attestation_id,
                    record.workspace_id,
                    record.actor_id,
                    record.session_id,
                    record.url_hash,
                    record.evidence_url,
                    record.evidence_hash,
                    json.dumps(record.allowed_purposes),
                    record.approved_by,
                    record.approved_at,
                    record.expires_at,
                ),
            )
        return record

    def revoke(
        self,
        attestation_id: str,
        *,
        admin_authority: DocumentAdminAuthority | None,
    ) -> None:
        _require_trusted_local()
        _require_admin(admin_authority)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE source_document_attestations SET revoked_at=?
                WHERE attestation_id=? AND revoked_at IS NULL
                """,
                (_now().isoformat(), attestation_id.strip()),
            )

    def require(
        self,
        *,
        attestation_id: str,
        context: TenantContext,
        url: str,
        purposes: Iterable[str],
    ) -> DocumentRightsAttestation:
        _require_trusted_local()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM source_document_attestations
                WHERE attestation_id=? AND revoked_at IS NULL
                """,
                (attestation_id.strip(),),
            ).fetchone()
        if row is None:
            raise SourceRightsDeniedError(
                "source-rights denied: document rights attestation is missing or revoked"
            )
        expected_hash = document_url_hash(url)
        comparisons = (
            (str(row["workspace_id"]), context.workspace_id),
            (str(row["actor_id"]), context.actor_id),
            (str(row["session_id"]), context.session_id),
            (str(row["url_hash"]), expected_hash),
        )
        if any(not hmac.compare_digest(left, right) for left, right in comparisons):
            raise SourceRightsDeniedError(
                "source-rights denied: document rights attestation scope mismatch"
            )
        if _parse_time(str(row["expires_at"])) <= _now():
            raise SourceRightsDeniedError(
                "source-rights denied: document rights attestation expired"
            )
        allowed = tuple(json.loads(str(row["allowed_purposes"])))
        requested = {str(item).strip().casefold() for item in purposes}
        if not requested or not requested.issubset(set(allowed)):
            raise SourceRightsDeniedError(
                "source-rights denied: document rights attestation lacks purpose"
            )
        return DocumentRightsAttestation(
            attestation_id=str(row["attestation_id"]),
            workspace_id=str(row["workspace_id"]),
            actor_id=str(row["actor_id"]),
            session_id=str(row["session_id"]),
            url_hash=str(row["url_hash"]),
            evidence_url=str(row["evidence_url"]),
            evidence_hash=str(row["evidence_hash"]),
            allowed_purposes=allowed,
            approved_by=str(row["approved_by"]),
            approved_at=str(row["approved_at"]),
            expires_at=str(row["expires_at"]),
        )


def require_external_document_attestation(
    url: str,
    attestation_id: str | None,
    *,
    purposes: Iterable[str] = DOCUMENT_PURPOSES,
    config: CreConfig | None = None,
) -> DocumentRightsAttestation | None:
    runtime_config = current_runtime_config()
    selected_config = runtime_config if runtime_config is not None else config
    registry = get_rights_registry(
        selected_config.source_rights_registry_path
        if selected_config is not None
        else None
    )
    classified = registry.for_url(url)
    if classified is not None or registry.has_registered_host(url):
        source_id = (
            classified.source_id
            if classified is not None
            else "a registered source host"
        )
        raise SourceRightsDeniedError(
            "source-rights denied: external-document attestation cannot reclassify "
            f"known source {source_id}"
        )
    if not is_hosted_execution(selected_config):
        external_record = require_source(
            "documents.external_url",
            config=selected_config,
        )
        if (
            external_record is None
            or external_record.source_id != "documents.external_url"
        ):
            raise SourceRightsDeniedError(
                "source-rights denied: external-document source record is missing"
            )
        return None
    context = current_context()
    if context is None or context.trusted:
        raise SourceRightsDeniedError(
            "source-rights denied: hosted document attestation context is missing"
        )
    if not context.actor_id.strip() or not context.session_id.strip():
        raise SourceRightsDeniedError(
            "source-rights denied: document attestation requires actor and session bindings"
        )
    if not attestation_id or not attestation_id.strip():
        raise SourceRightsDeniedError(
            "source-rights denied: document rights attestation is required"
        )
    repository = _hosted_repository.get()
    if repository is None:
        raise SourceRightsDeniedError(
            "source-rights denied: hosted document attestation requires an "
            "injected durable repository; local SQLite authority is prohibited"
        )
    return repository.require(
        attestation_id=attestation_id,
        context=context,
        url=url,
        purposes=purposes,
    )


__all__ = [
    "DOCUMENT_PURPOSES",
    "DocumentAttestationStore",
    "DocumentAdminAuthority",
    "DocumentAttestationRepository",
    "DocumentRightsAttestation",
    "document_url_hash",
    "normalized_document_url",
    "issue_document_admin_authority",
    "require_external_document_attestation",
    "use_hosted_document_attestation_repository",
]
