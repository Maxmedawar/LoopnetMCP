"""Validated, redaction-safe PostgreSQL runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _positive(value: int | float, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, repr=False)
class PostgresSettings:
    """Bounded pool settings without a printable connection string."""

    dsn: str
    min_size: int = 1
    max_size: int = 8
    acquire_timeout: float = 10.0
    max_waiting: int = 32
    max_lifetime: float = 1800.0
    max_idle: float = 300.0
    reconnect_timeout: float = 15.0
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000
    idle_transaction_timeout_ms: int = 30_000
    application_name: str = "medawarcre"
    runtime_mode: str = "app"

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("database DSN is required")
        if self.min_size < 0:
            raise ValueError("min_size cannot be negative")
        if self.max_size <= 0:
            raise ValueError("max_size must be positive")
        if self.max_size < self.min_size:
            raise ValueError("max_size must be greater than or equal to min_size")
        if self.max_waiting <= 0:
            raise ValueError("max_waiting must be positive")
        for value, name in (
            (self.acquire_timeout, "acquire_timeout"),
            (self.max_lifetime, "max_lifetime"),
            (self.max_idle, "max_idle"),
            (self.reconnect_timeout, "reconnect_timeout"),
            (self.statement_timeout_ms, "statement_timeout_ms"),
            (self.lock_timeout_ms, "lock_timeout_ms"),
            (self.idle_transaction_timeout_ms, "idle_transaction_timeout_ms"),
        ):
            _positive(value, name)
        if not self.application_name.strip():
            raise ValueError("application_name is required")
        if self.runtime_mode not in {"app", "admin"}:
            raise ValueError("runtime_mode must be app or admin")

    def __repr__(self) -> str:
        return (
            "PostgresSettings(dsn=<redacted>, "
            f"min_size={self.min_size}, max_size={self.max_size}, "
            f"acquire_timeout={self.acquire_timeout}, runtime_mode={self.runtime_mode!r})"
        )

    @classmethod
    def from_env(cls, prefix: str = "MEDAWARCRE_POSTGRES_") -> "PostgresSettings":
        dsn = os.environ.get("MEDAWARCRE_DATABASE_URL", "")

        def integer(name: str, default: int) -> int:
            raw = os.environ.get(prefix + name)
            return default if raw is None else int(raw)

        def number(name: str, default: float) -> float:
            raw = os.environ.get(prefix + name)
            return default if raw is None else float(raw)

        return cls(
            dsn=dsn,
            min_size=integer("MIN_SIZE", 1),
            max_size=integer("MAX_SIZE", 8),
            acquire_timeout=number("ACQUIRE_TIMEOUT", 10.0),
            max_waiting=integer("MAX_WAITING", 32),
            max_lifetime=number("MAX_LIFETIME", 1800.0),
            max_idle=number("MAX_IDLE", 300.0),
            reconnect_timeout=number("RECONNECT_TIMEOUT", 15.0),
            statement_timeout_ms=integer("STATEMENT_TIMEOUT_MS", 30_000),
            lock_timeout_ms=integer("LOCK_TIMEOUT_MS", 5_000),
            idle_transaction_timeout_ms=integer(
                "IDLE_TRANSACTION_TIMEOUT_MS", 30_000
            ),
            application_name=os.environ.get(
                prefix + "APPLICATION_NAME", "medawarcre"
            ),
            runtime_mode=os.environ.get(prefix + "RUNTIME_MODE", "app"),
        )


__all__ = ["PostgresSettings"]
