"""Psycopg 3 pool with transaction-local authorization context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from cre_mcp.postgres.authority import (
    UnsafeDatabaseRoleError,
    assert_exact_group_session,
)
from cre_mcp.postgres.config import PostgresSettings

INTERNAL_ROLES = frozenset(
    {
        "owner",
        "admin",
        "jv_operations",
        "support",
        "security_audit",
        "read_only_analyst",
    }
)
_CONTEXT_KEYS = (
    "app.workspace_id",
    "app.actor_user_id",
    "app.internal_role",
    "app.audit_reason",
)


class UnsafeRuntimeRoleError(RuntimeError):
    """Raised when a runtime DSN could bypass the intended RLS boundary."""


def _uuid(value: str | UUID, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"{name} must be a UUID") from error


@dataclass(frozen=True)
class AuthorityContext:
    workspace_id: str | None
    actor_user_id: str
    internal_role: str | None = None
    audit_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workspace_id",
            None
            if self.workspace_id is None
            else _uuid(self.workspace_id, "workspace_id"),
        )
        object.__setattr__(
            self, "actor_user_id", _uuid(self.actor_user_id, "actor_user_id")
        )
        if self.internal_role is None:
            if self.audit_reason is not None:
                raise ValueError("audit_reason requires an internal role")
            if self.workspace_id is None:
                raise ValueError("tenant context requires workspace_id")
            return
        normalized_role = self.internal_role.strip().casefold()
        if normalized_role not in INTERNAL_ROLES:
            raise ValueError("unsupported internal role")
        normalized_reason = (self.audit_reason or "").strip()
        if len(normalized_reason) < 3:
            raise ValueError("internal context requires an audit reason")
        object.__setattr__(self, "internal_role", normalized_role)
        object.__setattr__(self, "audit_reason", normalized_reason)

    @classmethod
    def tenant(
        cls, workspace_id: str | UUID, actor_user_id: str | UUID
    ) -> "AuthorityContext":
        return cls(str(workspace_id), str(actor_user_id))

    @classmethod
    def internal(
        cls,
        actor_user_id: str | UUID,
        role: str,
        reason: str,
        *,
        workspace_id: str | UUID | None = None,
    ) -> "AuthorityContext":
        return cls(
            None if workspace_id is None else str(workspace_id),
            str(actor_user_id),
            role,
            reason,
        )


@dataclass(frozen=True)
class DatabaseReadinessSnapshot:
    """Fixed, read-only catalog inputs exposed to the readiness evaluator."""

    server_version: int
    history: tuple[tuple[object, ...], ...]
    tables: frozenset[str]
    rls_tables: frozenset[str]
    invalid_foreign_keys: int
    catalog_fingerprint: str


class PostgresDatabase:
    """Bounded synchronous pool suitable for dispatch through ``to_thread``."""

    def __init__(self, settings: PostgresSettings) -> None:
        self.settings = settings
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
            name="medawarcre-runtime",
        )

    def _configure(self, connection: psycopg.Connection) -> None:
        self._pin_search_path(connection)
        self._assert_runtime_role(connection)
        connection.execute("SET TIME ZONE 'UTC'")
        connection.execute(
            "SELECT set_config('application_name', %s, false), "
            "set_config('search_path', 'pg_catalog', false), "
            "set_config('statement_timeout', %s, false), "
            "set_config('lock_timeout', %s, false), "
            "set_config('idle_in_transaction_session_timeout', %s, false)",
            (
                self.settings.application_name,
                f"{self.settings.statement_timeout_ms}ms",
                f"{self.settings.lock_timeout_ms}ms",
                f"{self.settings.idle_transaction_timeout_ms}ms",
            ),
        )
        connection.commit()

    @staticmethod
    def _pin_search_path(connection: psycopg.Connection) -> None:
        connection.execute("SET search_path TO pg_catalog")

    def _assert_runtime_role(self, connection: psycopg.Connection) -> None:
        expected_role = (
            "medawarcre_app"
            if self.settings.runtime_mode == "app"
            else "medawarcre_admin"
        )
        try:
            assert_exact_group_session(
                connection,
                expected_role,
                login_inherits=True,
                group_inherits=True,
            )
        except UnsafeDatabaseRoleError as error:
            raise UnsafeRuntimeRoleError(
                "runtime database role violates the least-privilege contract"
            ) from error

    @staticmethod
    def _reset(connection: psycopg.Connection) -> None:
        connection.execute("SET search_path TO pg_catalog")
        for key in _CONTEXT_KEYS:
            connection.execute(
                "SELECT set_config(%s, '', false)",
                (key,),
            )
        connection.commit()

    def open(self, *, wait: bool = True) -> None:
        with psycopg.connect(self.settings.dsn) as connection:
            self._pin_search_path(connection)
            self._assert_runtime_role(connection)
        self._pool.open(wait=wait)

    def close(self) -> None:
        self._pool.close()

    @property
    def closed(self) -> bool:
        return self._pool.closed

    def liveness_probe(self) -> bool:
        """Run the one fixed liveness query without exposing a connection."""
        with self._pool.connection(
            timeout=self.settings.acquire_timeout
        ) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return connection.execute("SELECT 1").fetchone() == (1,)

    def readiness_snapshot(self) -> DatabaseReadinessSnapshot:
        """Collect the fixed read-only schema diagnostics used at readiness."""
        from cre_mcp.postgres.catalog import catalog_fingerprint

        with self._pool.connection(
            timeout=self.settings.acquire_timeout
        ) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                history = tuple(
                    tuple(row)
                    for row in connection.execute(
                        "SELECT version,description,checksum,state,dirty "
                        "FROM medawarcre.schema_migrations ORDER BY version"
                    ).fetchall()
                )
                tables = frozenset(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT c.relname FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='medawarcre' AND c.relkind IN ('r','p')"
                    )
                )
                rls_tables = frozenset(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT c.relname FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='medawarcre' AND c.relrowsecurity"
                    )
                )
                invalid_foreign_keys = int(
                    connection.execute(
                        "SELECT count(*) FROM pg_catalog.pg_constraint c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid=c.connamespace "
                        "WHERE n.nspname='medawarcre' AND c.contype='f' "
                        "AND NOT c.convalidated"
                    ).fetchone()[0]
                )
                fingerprint = catalog_fingerprint(connection)
                return DatabaseReadinessSnapshot(
                    server_version=int(connection.info.server_version),
                    history=history,
                    tables=tables,
                    rls_tables=rls_tables,
                    invalid_foreign_keys=invalid_foreign_keys,
                    catalog_fingerprint=fingerprint,
                )

    @contextmanager
    def connection(
        self, context: AuthorityContext | None = None
    ) -> Iterator[psycopg.Connection]:
        if context is None:
            if self.settings.runtime_mode == "app":
                raise ValueError("app pool requires tenant authority")
            raise ValueError("admin pool requires internal authority")
        if (
            self.settings.runtime_mode == "app"
            and context.internal_role is not None
        ):
            raise ValueError("app pool cannot accept internal authority")
        if (
            self.settings.runtime_mode == "admin"
            and context.internal_role is None
        ):
            raise ValueError("admin pool requires internal authority")
        values = {
            "app.workspace_id": (
                "" if context.workspace_id is None else context.workspace_id
            ),
            "app.actor_user_id": context.actor_user_id,
            "app.internal_role": (
                "" if context.internal_role is None else context.internal_role
            ),
            "app.audit_reason": (
                "" if context.audit_reason is None else context.audit_reason
            ),
        }
        with self._pool.connection(
            timeout=self.settings.acquire_timeout
        ) as connection:
            with connection.transaction():
                for key, value in values.items():
                    connection.execute(
                        "SELECT set_config(%s, %s, true)", (key, value)
                    )
                yield connection

    def stats(self) -> dict[str, int]:
        return dict(self._pool.get_stats())


__all__ = [
    "AuthorityContext",
    "DatabaseReadinessSnapshot",
    "INTERNAL_ROLES",
    "PostgresDatabase",
    "UnsafeRuntimeRoleError",
]
