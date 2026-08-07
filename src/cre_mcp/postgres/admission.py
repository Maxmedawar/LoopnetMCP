"""Dedicated PostgreSQL repository for atomic hosted request admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from cre_mcp.access.arguments import canonical_argument_hash
from cre_mcp.access.context import TenantContext
from cre_mcp.access.quota import is_canonical_quota_bucket
from cre_mcp.platform.auth import DEFAULT_AUDIENCE, DEFAULT_RESOURCE
from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_admission_object_authority,
    assert_admission_session,
)
from cre_mcp.postgres.config import PostgresSettings

_ADMIT_QUERY = """
SELECT *
FROM medawarcre.atomic_admit_tool_call(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""
_FINAL_QUERY = """
SELECT medawarcre.record_tool_call_final(
    %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


class AdmissionUnavailable(RuntimeError):
    """The admission repository cannot complete its exact safe operation."""


def _uuid(value: str | UUID, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"{field} must be a UUID") from error


@dataclass(frozen=True)
class AdmissionOutcome:
    invocation_id: str
    request_correlation_id: str
    workspace_public_id: str
    actor_user_id: str
    session_id: str
    tool_name: str
    decision: Literal["allowed", "denied", "approval_required"]
    reason_code: str
    safe_reason: str
    approval_id: str | None = None
    quota_used: int | None = None
    replayed: bool = False
    finalized: bool = False


class PostgresAdmissionRepository:
    """Expose only atomic admission and its bound final-audit operation."""

    def __init__(
        self,
        settings: PostgresSettings,
        *,
        audience: str = DEFAULT_AUDIENCE,
        resource: str = DEFAULT_RESOURCE,
    ) -> None:
        self.settings = settings
        self.audience = audience.strip()
        self.resource = resource.strip()
        if not self.audience or not self.resource:
            raise ValueError("admission audience and resource are required")
        self._pool = ConnectionPool(
            conninfo=settings.dsn,
            min_size=settings.min_size,
            max_size=settings.max_size,
            timeout=settings.acquire_timeout,
            max_waiting=settings.max_waiting,
            max_lifetime=settings.max_lifetime,
            max_idle=settings.max_idle,
            reconnect_timeout=settings.reconnect_timeout,
            open=False,
            configure=self._configure,
            check=ConnectionPool.check_connection,
            reset=self._reset,
            name="medawarcre-admission",
        )

    def __repr__(self) -> str:
        return (
            "PostgresAdmissionRepository(dsn=<redacted>, "
            f"min_size={self.settings.min_size}, "
            f"max_size={self.settings.max_size})"
        )

    @classmethod
    def from_env(cls) -> "PostgresAdmissionRepository":
        settings = PostgresSettings.from_env(
            "MEDAWARCRE_ADMISSION_POSTGRES_",
            dsn_env="MEDAWARCRE_ADMISSION_DATABASE_URL",
        )
        if settings.application_name == "medawarcre":
            settings = PostgresSettings(
                dsn=settings.dsn,
                min_size=settings.min_size,
                max_size=settings.max_size,
                acquire_timeout=settings.acquire_timeout,
                max_waiting=settings.max_waiting,
                max_lifetime=settings.max_lifetime,
                max_idle=settings.max_idle,
                reconnect_timeout=settings.reconnect_timeout,
                statement_timeout_ms=settings.statement_timeout_ms,
                lock_timeout_ms=settings.lock_timeout_ms,
                idle_transaction_timeout_ms=settings.idle_transaction_timeout_ms,
                application_name="medawarcre-admission",
                runtime_mode=settings.runtime_mode,
            )
        return cls(settings)

    @staticmethod
    def _pin_search_path(connection: psycopg.Connection) -> None:
        connection.execute("SET search_path TO pg_catalog")

    def _configure(self, connection: psycopg.Connection) -> None:
        self._pin_search_path(connection)
        assert_admission_session(connection)
        assert_admission_object_authority(connection)
        connection.execute("SET TIME ZONE 'UTC'")
        connection.execute(
            "SELECT pg_catalog.set_config('application_name', %s, false), "
            "pg_catalog.set_config('search_path', 'pg_catalog', false), "
            "pg_catalog.set_config('statement_timeout', %s, false), "
            "pg_catalog.set_config('lock_timeout', %s, false), "
            "pg_catalog.set_config('idle_in_transaction_session_timeout', %s, false)",
            (
                self.settings.application_name,
                f"{self.settings.statement_timeout_ms}ms",
                f"{self.settings.lock_timeout_ms}ms",
                f"{self.settings.idle_transaction_timeout_ms}ms",
            ),
        )
        connection.commit()

    @staticmethod
    def _reset(connection: psycopg.Connection) -> None:
        connection.execute("RESET ROLE")
        connection.execute("SET search_path TO pg_catalog")
        connection.commit()

    def open(self, *, wait: bool = True) -> None:
        try:
            with psycopg.connect(self.settings.dsn) as connection:
                self._pin_search_path(connection)
                assert_admission_session(connection)
                assert_admission_object_authority(connection)
            self._pool.open(wait=wait)
        except UnsafeDatabaseRoleError as error:
            raise AdmissionUnavailable(
                "admission database login violates the authority contract"
            ) from error
        except AdmissionUnavailable:
            raise
        except Exception as error:
            # Not chained: psycopg echoes a DSN it cannot parse as a URL, so the
            # cause would carry this credential into every traceback. See the
            # same treatment in postgres/runtime.py.
            raise AdmissionUnavailable(
                f"admission database is unavailable ({type(error).__name__})"
            ) from None

    def close(self) -> None:
        self._pool.close()

    @property
    def closed(self) -> bool:
        return self._pool.closed

    def admit(
        self,
        context: TenantContext,
        tool_name: str,
        arguments: dict,
        *,
        quota_bucket: str | None,
        requires_approval: bool,
        approval_token: str | None = None,
        invocation_id: str | UUID | None = None,
        request_correlation_id: str | UUID | None = None,
    ) -> AdmissionOutcome:
        if context.trusted:
            raise ValueError("trusted local authority cannot use hosted admission")
        normalized_tool = tool_name.strip() if isinstance(tool_name, str) else ""
        if not normalized_tool:
            raise ValueError("tool_name is required")
        if type(requires_approval) is not bool:
            raise ValueError("requires_approval must be boolean")
        if quota_bucket is not None and not is_canonical_quota_bucket(quota_bucket):
            raise ValueError("quota_bucket must be a canonical identifier")
        if approval_token is not None:
            if not isinstance(approval_token, str) or not approval_token:
                raise ValueError("approval_token must be a non-empty string")
            if not requires_approval:
                raise ValueError("approval_token requires an approval gate")
            try:
                approval_token_bytes = approval_token.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ValueError("approval_token must be valid UTF-8") from error
        else:
            approval_token_bytes = None
        invocation = _uuid(invocation_id or uuid4(), "invocation_id")
        request_id = _uuid(
            request_correlation_id or uuid4(),
            "request_correlation_id",
        )
        actor_id = _uuid(context.actor_id, "actor_user_id")
        session_id = _uuid(context.session_id, "session_id")
        args_hash = canonical_argument_hash(arguments)
        approval_hash = (
            None
            if approval_token_bytes is None
            else hashlib.sha256(approval_token_bytes).digest()
        )
        try:
            with self._pool.connection(
                timeout=self.settings.acquire_timeout
            ) as connection:
                with connection.transaction():
                    assert_admission_session(connection)
                    assert_admission_object_authority(connection)
                    connection.execute("SET LOCAL ROLE medawarcre_admission")
                    with connection.cursor(row_factory=dict_row) as cursor:
                        row = cursor.execute(
                            _ADMIT_QUERY,
                            (
                                invocation,
                                request_id,
                                context.workspace_id,
                                actor_id,
                                session_id,
                                self.audience,
                                self.resource,
                                context.profile.value,
                                context.plan,
                                list(context.territories),
                                normalized_tool,
                                args_hash,
                                quota_bucket,
                                requires_approval,
                                approval_hash,
                            ),
                        ).fetchone()
        except UnsafeDatabaseRoleError as error:
            raise AdmissionUnavailable(
                "admission database login violates the authority contract"
            ) from error
        except AdmissionUnavailable:
            raise
        except Exception as error:
            raise AdmissionUnavailable("request admission failed closed") from error
        if row is None:
            raise AdmissionUnavailable("request admission binding was rejected")
        return self._outcome(
            row,
            invocation=invocation,
            request_id=request_id,
            workspace_public_id=context.workspace_id,
            actor_id=actor_id,
            session_id=session_id,
            tool_name=normalized_tool,
        )

    @staticmethod
    def _outcome(
        row: dict,
        *,
        invocation: str,
        request_id: str,
        workspace_public_id: str,
        actor_id: str,
        session_id: str,
        tool_name: str,
    ) -> AdmissionOutcome:
        database_decision = row.get("decision")
        reason_code = row.get("reason_code")
        safe_reason = row.get("safe_reason")
        if database_decision not in {"allowed", "denied"}:
            raise AdmissionUnavailable("admission database returned an invalid decision")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise AdmissionUnavailable("admission database returned an invalid reason")
        if not isinstance(safe_reason, str) or not safe_reason.strip():
            raise AdmissionUnavailable("admission database returned an invalid message")
        decision: Literal["allowed", "denied", "approval_required"]
        decision = (
            "approval_required"
            if database_decision == "denied" and reason_code == "approval_required"
            else database_decision
        )
        raw_approval_id = row.get("approval_request_id")
        try:
            approval_id = (
                None
                if raw_approval_id is None
                else _uuid(raw_approval_id, "approval_request_id")
            )
        except ValueError as error:
            raise AdmissionUnavailable(
                "admission database returned an invalid approval binding"
            ) from error
        if (decision == "approval_required") != (approval_id is not None):
            raise AdmissionUnavailable("admission approval binding is invalid")
        raw_quota = row.get("quota_used")
        try:
            quota_used = None if raw_quota is None else int(raw_quota)
        except (TypeError, ValueError, OverflowError) as error:
            raise AdmissionUnavailable(
                "admission database returned an invalid quota result"
            ) from error
        if quota_used is not None and quota_used < 1:
            raise AdmissionUnavailable("admission quota result is invalid")
        replayed = row.get("replayed")
        finalized = row.get("finalized")
        if type(replayed) is not bool or type(finalized) is not bool:
            raise AdmissionUnavailable("admission replay state is invalid")
        if finalized and (not replayed or decision != "allowed"):
            raise AdmissionUnavailable("admission finalization state is invalid")
        return AdmissionOutcome(
            invocation_id=invocation,
            request_correlation_id=request_id,
            workspace_public_id=workspace_public_id,
            actor_user_id=actor_id,
            session_id=session_id,
            tool_name=tool_name,
            decision=decision,
            reason_code=reason_code,
            safe_reason=safe_reason,
            approval_id=approval_id,
            quota_used=quota_used,
            replayed=replayed,
            finalized=finalized,
        )

    def record_final(
        self,
        admission: AdmissionOutcome,
        *,
        succeeded: bool,
        reason_code: str,
        safe_reason: str,
    ) -> str:
        if admission.decision != "allowed":
            raise ValueError("final audit requires an allowed admission")
        if admission.replayed or admission.finalized:
            raise ValueError("final audit requires the fresh execution owner")
        if type(succeeded) is not bool:
            raise ValueError("succeeded must be boolean")
        normalized_code = reason_code.strip() if isinstance(reason_code, str) else ""
        normalized_reason = safe_reason.strip() if isinstance(safe_reason, str) else ""
        if not normalized_code or not normalized_reason:
            raise ValueError("final audit reason is required")
        try:
            with self._pool.connection(
                timeout=self.settings.acquire_timeout
            ) as connection:
                with connection.transaction():
                    assert_admission_session(connection)
                    assert_admission_object_authority(connection)
                    connection.execute("SET LOCAL ROLE medawarcre_admission")
                    row = connection.execute(
                        _FINAL_QUERY,
                        (
                            admission.invocation_id,
                            admission.request_correlation_id,
                            admission.workspace_public_id,
                            admission.actor_user_id,
                            admission.session_id,
                            admission.tool_name,
                            succeeded,
                            normalized_code,
                            normalized_reason,
                        ),
                    ).fetchone()
        except UnsafeDatabaseRoleError as error:
            raise AdmissionUnavailable(
                "admission database login violates the authority contract"
            ) from error
        except AdmissionUnavailable:
            raise
        except Exception as error:
            raise AdmissionUnavailable("final decision audit failed closed") from error
        if row is None or row[0] is None:
            raise AdmissionUnavailable("final decision binding was rejected")
        try:
            return _uuid(row[0], "final_audit_id")
        except ValueError as error:
            raise AdmissionUnavailable(
                "final decision audit returned an invalid binding"
            ) from error


__all__ = [
    "AdmissionOutcome",
    "AdmissionUnavailable",
    "PostgresAdmissionRepository",
]
