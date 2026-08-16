"""The one connection seam every platform store opens its database through.

Every store in ``cre_mcp.platform`` was written against ``sqlite3`` directly:
``?`` placeholders, ``PRAGMA``, ``BEGIN IMMEDIATE``, ``sqlite3.Row``, and
``sqlite3.IntegrityError``. That is correct for the local stdio product, which
deliberately keeps its file-backed stores, and wrong for the hosted process,
whose authority may not live in a SQLite file.

This module is the seam between those two facts. It owns the exact connection
setup the stores used to perform inline, and it consults a process-level
backend registry. With no backend installed — the local stdio default and the
default in every test — it returns precisely the ``sqlite3`` connection the
store would have opened itself. With the PostgreSQL backend installed by
``cre_mcp.postgres.platform_bridge``, it returns a connection that presents the
same DB-API surface and speaks to PostgreSQL.

The registry is deliberately process-level rather than per-store. A hosted
process has exactly one authority backend, and a store that could be pointed at
a different one than its neighbour is a split-brain waiting to happen: the
authority resolver and the session store must agree about what a session is.
Installing a backend twice without clearing it is refused for the same reason.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, runtime_checkable


class PlatformBackendConflict(RuntimeError):
    """A second, different platform backend was installed over a live one."""


@runtime_checkable
class PlatformBackend(Protocol):
    """One durable backend for every platform store in this process."""

    def connect(
        self, *, timeout: float, transactional: bool
    ) -> Any:  # pragma: no cover - protocol
        """Return a context manager yielding one DB-API connection."""


_BACKEND: PlatformBackend | None = None
_BACKEND_LOCK = Lock()


def install_platform_backend(backend: PlatformBackend) -> None:
    """Install the process-wide platform backend, refusing a silent swap."""
    global _BACKEND
    if backend is None:
        raise ValueError("a platform backend is required")
    with _BACKEND_LOCK:
        if _BACKEND is not None and _BACKEND is not backend:
            raise PlatformBackendConflict(
                "a different platform backend is already installed"
            )
        _BACKEND = backend


def clear_platform_backend() -> None:
    """Return this process to the file-backed default."""
    global _BACKEND
    with _BACKEND_LOCK:
        _BACKEND = None


def current_platform_backend() -> PlatformBackend | None:
    """Return the installed backend, or None for the file-backed default."""
    with _BACKEND_LOCK:
        return _BACKEND


def platform_backend_is_remote() -> bool:
    """True when platform authority is not a local file."""
    return current_platform_backend() is not None


def is_remote_connection(connection: Any) -> bool:
    """True when this connection is not a real ``sqlite3`` connection.

    Schema-creating code paths use this to skip DDL they do not own. On the
    remote backend the schema is owned by a numbered PostgreSQL migration, not
    by whichever store happened to open a connection first.
    """
    return not isinstance(connection, sqlite3.Connection)


@contextmanager
def platform_connection(
    db_path: str | Path,
    *,
    timeout: float = 30.0,
    transactional: bool = True,
    ensure_parent: bool = False,
    journal_wal: bool = False,
) -> Iterator[Any]:
    """Yield one platform connection from the installed backend.

    ``transactional`` reproduces ``with connection:`` — commit on a clean exit,
    roll back on an exception, without closing. Two stores deliberately do not
    use it and manage their own transactions; they pass ``False``.

    ``ensure_parent`` and ``journal_wal`` are SQLite-only setup that some stores
    performed and others did not. They are preserved exactly rather than
    normalised, because normalising them here would change local behaviour in a
    change whose subject is the hosted path.
    """
    backend = current_platform_backend()
    if backend is not None:
        with backend.connect(timeout=timeout, transactional=transactional) as (
            connection
        ):
            yield connection
        return

    path = Path(db_path).expanduser()
    if ensure_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=timeout)
    try:
        connection.row_factory = sqlite3.Row
        if journal_wal:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        if transactional:
            with connection:
                yield connection
        else:
            yield connection
    finally:
        connection.close()


__all__ = [
    "PlatformBackend",
    "PlatformBackendConflict",
    "clear_platform_backend",
    "current_platform_backend",
    "install_platform_backend",
    "is_remote_connection",
    "platform_backend_is_remote",
    "platform_connection",
]
