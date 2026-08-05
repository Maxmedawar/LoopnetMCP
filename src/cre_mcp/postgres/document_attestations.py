"""Request-scoped PostgreSQL authority for external document attestations."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from cre_mcp.access.context import TenantContext, current_context
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.domains import (
    current_hosted_request_repositories,
    require_fresh_admission,
)
from cre_mcp.postgres.pool import PostgresDatabase
from cre_mcp.source_rights.attestations import (
    DOCUMENT_PURPOSES,
    DocumentRightsAttestation,
    document_url_hash,
)
from cre_mcp.source_rights.gate import SourceRightsDeniedError

_MISSING = "source-rights denied: document rights attestation is missing or revoked"
_SCOPE = "source-rights denied: document rights attestation scope mismatch"
_EXPIRED = "source-rights denied: document rights attestation expired"
_PURPOSE = "source-rights denied: document rights attestation lacks purpose"
_REQUEST_SCOPE = "source-rights denied: document repository request scope is inactive"
_UNAVAILABLE = "source-rights denied: document attestation authority unavailable"


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("document attestation timestamp is malformed")
    return value.astimezone(UTC).isoformat()


def _digest_hex(value: Any) -> str:
    raw = bytes(value)
    if len(raw) != 32:
        raise ValueError("document attestation digest is malformed")
    return raw.hex()


class PostgresDocumentAttestationRepository:
    """Read one attestation through an exact admitted app transaction."""

    def __init__(
        self,
        database: PostgresDatabase,
        admission: AdmissionOutcome,
    ) -> None:
        if not isinstance(database, PostgresDatabase):
            raise TypeError("document attestation repository requires PostgreSQL")
        self._database = database
        self._admission = require_fresh_admission(admission)

    def _require_active_scope(self, context: TenantContext) -> None:
        repositories = current_hosted_request_repositories()
        active_context = current_context()
        if (
            repositories is None
            or repositories.admission is not self._admission
            or repositories.require("document") is not self
            or active_context is not context
            or context.trusted
        ):
            raise SourceRightsDeniedError(_REQUEST_SCOPE)
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
            raise SourceRightsDeniedError(_SCOPE)

    def require(
        self,
        *,
        attestation_id: str,
        context: TenantContext,
        url: str,
        purposes: Iterable[str],
    ) -> DocumentRightsAttestation:
        """Return the exact live record or deny without local fallback."""
        if not isinstance(context, TenantContext):
            raise SourceRightsDeniedError(_SCOPE)
        self._require_active_scope(context)
        selected_id = str(attestation_id).strip()
        requested = {str(item).strip().casefold() for item in purposes}
        if not selected_id:
            raise SourceRightsDeniedError(_MISSING)
        if not requested or not requested.issubset(DOCUMENT_PURPOSES):
            raise SourceRightsDeniedError(_PURPOSE)
        try:
            expected_hash = document_url_hash(url)
        except (TypeError, ValueError) as error:
            raise SourceRightsDeniedError(_SCOPE) from error

        try:
            with self._database.admitted_connection(self._admission) as connection:
                row = connection.execute(
                    "SELECT attestation.attestation_id,workspace.public_id,"
                    "attestation.actor_user_id::text,"
                    "attestation.oauth_session_id::text,attestation.url_hash,"
                    "attestation.evidence_url,attestation.evidence_hash,"
                    "attestation.allowed_purposes,attestation.approved_by::text,"
                    "attestation.approved_at,attestation.expires_at,"
                    "attestation.revoked_at "
                    "FROM medawarcre.source_document_attestations attestation "
                    "JOIN medawarcre.workspaces workspace "
                    "ON workspace.id=attestation.workspace_id "
                    "WHERE attestation.attestation_id=%s",
                    (selected_id,),
                ).fetchone()
        except Exception as error:
            raise SourceRightsDeniedError(_UNAVAILABLE) from error

        if row is None or row[11] is not None:
            raise SourceRightsDeniedError(_MISSING)
        try:
            allowed = tuple(sorted(str(item) for item in row[7]))
            record = DocumentRightsAttestation(
                attestation_id=str(row[0]),
                workspace_id=str(row[1]),
                actor_id=str(row[2]),
                session_id=str(row[3]),
                url_hash=_digest_hex(row[4]),
                evidence_url=str(row[5]),
                evidence_hash=_digest_hex(row[6]),
                allowed_purposes=allowed,
                approved_by=str(row[8]),
                approved_at=_utc_text(row[9]),
                expires_at=_utc_text(row[10]),
            )
        except Exception as error:
            raise SourceRightsDeniedError(_UNAVAILABLE) from error

        comparisons = (
            (record.workspace_id, context.workspace_id),
            (record.actor_id, context.actor_id),
            (record.session_id, context.session_id),
            (record.url_hash, expected_hash),
        )
        if any(not hmac.compare_digest(left, right) for left, right in comparisons):
            raise SourceRightsDeniedError(_SCOPE)
        if row[10] <= datetime.now(UTC):
            raise SourceRightsDeniedError(_EXPIRED)
        if (
            not allowed
            or not set(allowed).issubset(DOCUMENT_PURPOSES)
            or not requested.issubset(set(allowed))
        ):
            raise SourceRightsDeniedError(_PURPOSE)
        return record


__all__ = ["PostgresDocumentAttestationRepository"]
