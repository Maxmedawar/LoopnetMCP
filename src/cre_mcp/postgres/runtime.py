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

from cre_mcp.platform.secrets import (
    ProductionSecretsUnavailable,
    verify_production_secrets,
)
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
    audit_log: Any
    domain_repository_provider: Any
    oauth_authority: Any = None
    admission_repository: Any = None
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


def build_postgres_hosted_persistence(
    config: Any | None = None,
) -> HostedPersistenceBundle:
    """Build the production bundle or reject startup before local state exists.

    Order matters and is deliberate:

    1. The production secret preflight runs before any connection attempt, so a
       deployment whose managed secret store has not injected a credential stops
       with the missing variable *names* rather than with a connection error
       whose real cause is a missing credential.
    2. The certified pool opens and schema readiness is checked. An unready
       database stops here, before any store exists to write to it.
    3. The PostgreSQL platform backend is installed **before** ``PlatformApi``
       is constructed. Every platform store resolves its backend at connect
       time through ``cre_mcp.platform.dbapi``, so installing first is what
       makes the twelve authority stores PostgreSQL-backed rather than
       file-backed. Constructing the API first would produce a process whose
       authority silently lived in a SQLite file — which is the exact failure
       this boundary exists to prevent, and it would look identical from
       outside.
    4. Only then are the audit sink and the domain repository provider built.

    Anything that fails after the backend is installed unwinds it, so a failed
    start cannot leave a half-installed backend behind for the next attempt.
    """

    from cre_mcp.config import CreConfig
    from cre_mcp.platform.dbapi import install_platform_backend
    from cre_mcp.postgres.access_audit import PostgresAccessAuditLog
    from cre_mcp.postgres.platform_bridge import PostgresPlatformBackend
    from cre_mcp.postgres.request_scope import HostedDomainRepositoryProvider

    try:
        verify_production_secrets()
    except ProductionSecretsUnavailable as error:
        # Chaining is safe here precisely because the raised message and the
        # chained cause both carry variable names and no credential value.
        raise HostedPersistenceUnavailable(str(error)) from error

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
        database.close()
        raise
    except Exception as error:
        database.close()
        # Deliberately not chained. psycopg echoes the token it could not parse,
        # and for a DSN it cannot read as a URL — one leading space is enough,
        # which is an ordinary managed-store or copy-paste artifact — that token
        # is the entire connection string, password included. Chaining puts it
        # in every formatted traceback and in any logging.exception() call. The
        # exception type is diagnostic and carries none of the input.
        raise HostedPersistenceUnavailable(
            f"hosted PostgreSQL is unavailable ({type(error).__name__})"
        ) from None

    selected_config = config if config is not None else CreConfig()
    backend = PostgresPlatformBackend(
        settings.dsn,
        min_size=settings.min_size,
        max_size=settings.max_size,
        timeout=settings.acquire_timeout,
    )
    installed = False
    try:
        backend.open(wait=True)
        install_platform_backend(backend)
        installed = True

        from cre_mcp.platform.api import PlatformApi

        platform_api = PlatformApi(selected_config)
        audit_log = PostgresAccessAuditLog(backend)
        provider = HostedDomainRepositoryProvider(
            database, config=selected_config
        )
        oauth_authority = _build_oauth_authority()
        admission_repository = _build_admission_repository()
    except HostedPersistenceUnavailable:
        _unwind(database, backend, installed)
        raise
    except Exception as error:
        _unwind(database, backend, installed)
        raise HostedPersistenceUnavailable(
            f"hosted platform authority is unavailable ({type(error).__name__})"
        ) from None

    def _close() -> None:
        _unwind(database, backend, True)
        for closable in (oauth_authority, admission_repository):
            closer = getattr(closable, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # pragma: no cover - shutdown is best effort
                    pass

    return HostedPersistenceBundle(
        platform_api=platform_api,
        audit_log=audit_log,
        domain_repository_provider=provider,
        oauth_authority=oauth_authority,
        admission_repository=admission_repository,
        backend="postgres",
        close_callback=_close,
    )


def _unwind(database: Any, backend: Any, installed: bool) -> None:
    """Return the process to the file-backed default and drop both pools."""
    from cre_mcp.platform.dbapi import clear_platform_backend

    if installed:
        clear_platform_backend()
    for closable in (backend, database):
        try:
            closable.close()
        except Exception:  # pragma: no cover - shutdown is best effort
            pass


def _build_oauth_authority() -> Any:
    """Open the OAuth authority on its own least-privilege DSN.

    Deliberately ``from_env`` rather than the application settings: this
    repository asserts an exact ``medawarcre_oauth`` group session and refuses
    the application role, so handing it ``MEDAWARCRE_DATABASE_URL`` fails to
    boot. The separation is the point — a compromised application connection
    cannot mint authority.
    """
    from cre_mcp.postgres.oauth_authority import (
        PostgresOAuthAuthorityRepository,
    )

    repository = PostgresOAuthAuthorityRepository.from_env()
    repository.open(wait=True)
    return repository


def _build_admission_repository() -> Any:
    """Open atomic admission on its own least-privilege DSN, for the same reason."""
    from cre_mcp.postgres.admission import PostgresAdmissionRepository

    repository = PostgresAdmissionRepository.from_env()
    repository.open(wait=True)
    return repository


__all__ = [
    "HostedPersistenceBundle",
    "HostedPersistenceUnavailable",
    "bind_persistence_lifespan",
    "build_postgres_hosted_persistence",
]
