"""Cache interfaces and implementations."""

from typing import Any, Protocol

from cre_mcp.cache.memory import TTLCache
from cre_mcp.cache.sqlite import SQLiteCache


class Cache(Protocol):
    """Minimal cache contract shared by memory and persistent caches."""

    def get(self, key: str) -> Any | None: ...

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None: ...

    def clear(self) -> None: ...


__all__ = ["Cache", "SQLiteCache", "TTLCache"]
