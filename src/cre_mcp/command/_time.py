"""Deterministic date normalization used by command-center modules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


def as_datetime(value: date | datetime | str | None = None) -> datetime:
    """Normalize a caller-supplied point in time to an aware UTC datetime."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("as_of cannot be blank")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    else:
        raise ValueError("as_of must be a date, datetime, ISO string, or omitted")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def maybe_datetime(value: Any) -> datetime | None:
    """Best-effort timestamp parse for persisted data."""
    if value is None:
        return None
    try:
        return as_datetime(str(value))
    except (TypeError, ValueError):
        return None


def days_left(value: Any, as_of: datetime) -> int | None:
    """Return whole calendar days until a persisted date/timestamp."""
    parsed = maybe_datetime(value)
    if parsed is None:
        return None
    return (parsed.date() - as_of.date()).days

