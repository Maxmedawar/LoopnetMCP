"""Fail-closed construction boundary for hosted persistence.

The local stdio product deliberately keeps its existing file-backed stores.
Hosted HTTP is different: it may receive persistence only through this bundle,
and the production builder accepts only the certified PostgreSQL path.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.health import check_readiness
from cre_mcp.postgres.migrations import load_migrations
from cre_mcp.postgres.pool import PostgresDatabase


class HostedPersistenceUnavailable(RuntimeError):
    """Hosted HTTP cannot start with a certified persistence bundle."""


@dataclass
class HostedPersistenceBundle:
    """All durable services required by one hosted server process."""

    platform_api: Any
    access_registry: Any
    audit_log: Any
    backend: str = "postgres"
    close_callback: Callable[[], None] = lambda: None
    _closed: bool = field(default=False, init=False, repr=False)
    _close_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self.close_callback()
            self._closed = True


def bind_persistence_lifespan(app: Any, bundle: HostedPersistenceBundle) -> Any:
    """Close a hosted bundle exactly once after its ASGI lifespan."""

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def persistence_lifespan(asgi_app: Any):
        try:
            async with original_lifespan(asgi_app):
                yield
        finally:
            bundle.close()

    app.router.lifespan_context = persistence_lifespan
    app.state.hosted_persistence = bundle
    return app


def build_postgres_hosted_persistence() -> HostedPersistenceBundle:
    """Build the production bundle or reject startup before local state exists.

    The certified pool and schema readiness checks are active now. Domain
    repository wiring is intentionally fail-closed until its parity phase is
    complete, so a healthy database alone cannot accidentally revive SQLite or
    file-backed hosted authority.
    """

    try:
        settings = PostgresSettings.from_env()
    except (TypeError, ValueError) as error:
        raise HostedPersistenceUnavailable(
            "hosted HTTP requires a valid PostgreSQL runtime configuration"
        ) from error

    database = PostgresDatabase(settings)
    try:
        database.open(wait=True)
        readiness = check_readiness(database, expected=load_migrations())
        if not readiness.ok:
            raise HostedPersistenceUnavailable(
                f"hosted PostgreSQL is not release-ready ({readiness.code})"
            )
    except HostedPersistenceUnavailable:
        raise
    except Exception as error:
        raise HostedPersistenceUnavailable(
            "hosted PostgreSQL is unavailable"
        ) from error
    finally:
        database.close()

    raise HostedPersistenceUnavailable(
        "hosted PostgreSQL domain repositories are not yet certified"
    )


__all__ = [
    "HostedPersistenceBundle",
    "HostedPersistenceUnavailable",
    "bind_persistence_lifespan",
    "build_postgres_hosted_persistence",
]
