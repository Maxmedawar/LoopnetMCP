"""Restricted PostgreSQL repository for one-snapshot OAuth authority."""

from __future__ import annotations

import hashlib
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from cre_mcp.access.context import TenantContext
from cre_mcp.access.profiles import Profile
from cre_mcp.access.quota import is_canonical_quota_bucket
from cre_mcp.platform.auth import (
    DEFAULT_AUDIENCE,
    DEFAULT_RESOURCE,
    AuthenticatedSession,
)
from cre_mcp.platform.authority import (
    AuthorityOutcome,
    InternalAdminAuthority,
    MembershipAuthority,
    WorkspaceAuthority,
)
from cre_mcp.platform.entitlements import AccountRecord, EffectiveAccess
from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_service_session,
)
from cre_mcp.postgres.config import PostgresSettings

_AUTHORITY_QUERY = """
SELECT *
FROM medawarcre.resolve_oauth_authority(%s, %s, %s)
"""


class OAuthAuthorityUnavailable(RuntimeError):
    """The dedicated OAuth authority repository cannot operate safely."""


def _quotas(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    parsed: dict[str, int] = {}
    for bucket, limit in value.items():
        if (
            not is_canonical_quota_bucket(bucket)
            or type(limit) is not int
            or limit < 0
        ):
            return None
        parsed[bucket] = limit
    return parsed


class PostgresOAuthAuthorityRepository:
    """Expose only the fixed live-authority resolution operation."""

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
            raise ValueError("OAuth audience and resource are required")
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
            name="medawarcre-oauth-authority",
        )

    def __repr__(self) -> str:
        return (
            "PostgresOAuthAuthorityRepository(dsn=<redacted>, "
            f"min_size={self.settings.min_size}, "
            f"max_size={self.settings.max_size})"
        )

    @classmethod
    def from_env(cls) -> "PostgresOAuthAuthorityRepository":
        settings = PostgresSettings.from_env(
            "MEDAWARCRE_OAUTH_POSTGRES_",
            dsn_env="MEDAWARCRE_OAUTH_DATABASE_URL",
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
                idle_transaction_timeout_ms=(
                    settings.idle_transaction_timeout_ms
                ),
                application_name="medawarcre-oauth",
                runtime_mode=settings.runtime_mode,
            )
        return cls(settings)

    @staticmethod
    def _pin_search_path(connection: psycopg.Connection) -> None:
        connection.execute("SET search_path TO pg_catalog")

    def _configure(self, connection: psycopg.Connection) -> None:
        self._pin_search_path(connection)
        assert_service_session(connection, "oauth")
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
                assert_service_session(connection, "oauth")
            self._pool.open(wait=wait)
        except UnsafeDatabaseRoleError as error:
            raise OAuthAuthorityUnavailable(
                "OAuth database login violates the authority contract"
            ) from error
        except OAuthAuthorityUnavailable:
            raise
        except Exception as error:
            raise OAuthAuthorityUnavailable(
                "OAuth authority database is unavailable"
            ) from error

    def close(self) -> None:
        self._pool.close()

    @property
    def closed(self) -> bool:
        return self._pool.closed

    def resolve(self, bearer_token: str) -> AuthorityOutcome | None:
        if not isinstance(bearer_token, str) or not bearer_token:
            return None
        token_hash = hashlib.sha256(bearer_token.encode("utf-8")).digest()
        try:
            with self._pool.connection(
                timeout=self.settings.acquire_timeout
            ) as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    assert_service_session(connection, "oauth")
                    connection.execute("SET LOCAL ROLE medawarcre_oauth")
                    with connection.cursor(row_factory=dict_row) as cursor:
                        row = cursor.execute(
                            _AUTHORITY_QUERY,
                            (token_hash, self.audience, self.resource),
                        ).fetchone()
        except UnsafeDatabaseRoleError as error:
            raise OAuthAuthorityUnavailable(
                "OAuth database login violates the authority contract"
            ) from error
        except OAuthAuthorityUnavailable:
            raise
        except Exception as error:
            raise OAuthAuthorityUnavailable(
                "OAuth authority resolution failed closed"
            ) from error
        if row is None:
            return None
        return self._outcome(row)

    @staticmethod
    def _outcome(row: dict[str, Any]) -> AuthorityOutcome:
        session = AuthenticatedSession(
            session_id=str(row["session_id"]),
            workspace_id=str(row["workspace_public_id"]),
            user_id=str(row["user_id"]),
            client_id=str(row["client_id"]),
            scopes=tuple(str(scope) for scope in row["scopes"]),
            audience=str(row["audience"]),
            resource=str(row["resource"]),
            access_expires_at=row["access_expires_at"],
        )
        workspace = WorkspaceAuthority(
            id=str(row["workspace_id"]),
            public_id=str(row["workspace_public_id"]),
            name=str(row["workspace_name"]),
            plan_id=(
                None
                if row["workspace_plan_id"] is None
                else str(row["workspace_plan_id"])
            ),
        )
        membership = MembershipAuthority(
            id=str(row["membership_id"]),
            user_id=str(row["user_id"]),
            role=str(row["membership_role"]),
        )
        account = None
        if row["account_state"] is not None:
            account = AccountRecord(
                workspace_id=str(row["workspace_id"]),
                state=str(row["account_state"]),
                reason=row["account_reason_code"],
                updated_at=row["account_updated_at"],
            )
        effective_access = None
        if row["profile"] is not None and row["plan_key"] is not None:
            effective_access = EffectiveAccess(
                workspace_id=str(row["workspace_id"]),
                profile=Profile(str(row["profile"])),
                plan_key=str(row["plan_key"]),
                grant_ids=tuple(str(item) for item in row["grant_ids"]),
                sources=tuple(str(item) for item in row["grant_sources"]),
                expires_at=row["grant_expires_at"],
            )
        quota_limits = _quotas(row["quota_limits"])
        reason = None if row["denial_reason"] is None else str(row["denial_reason"])
        context = None
        if reason is None and effective_access is not None and quota_limits is not None:
            context = TenantContext(
                workspace_id=str(row["workspace_public_id"]),
                profile=effective_access.profile,
                plan=effective_access.plan_key,
                quota_limits=quota_limits,
                territories=tuple(str(item) for item in row["territories"]),
                active=True,
                trusted=False,
                display_name=str(row["workspace_name"]),
                actor_id=str(row["user_id"]),
                session_id=str(row["session_id"]),
            )
        if reason is None and context is None:
            reason = "plan_missing_or_invalid"
        internal_admin = None
        if row["internal_admin_role"] is not None:
            internal_admin = InternalAdminAuthority(
                user_id=str(row["user_id"]),
                role=str(row["internal_admin_role"]),
            )
        return AuthorityOutcome(
            session=session,
            workspace=workspace,
            membership=membership,
            account=account,
            effective_access=effective_access,
            context=context,
            reason=reason,
            internal_admin=internal_admin,
            jv_grant_present=bool(row["jv_grant_present"]),
        )


__all__ = [
    "OAuthAuthorityUnavailable",
    "PostgresOAuthAuthorityRepository",
]
