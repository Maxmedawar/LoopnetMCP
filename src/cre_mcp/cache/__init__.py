"""Cache interfaces and implementations."""

from typing import Any, Protocol

from cre_mcp.cache.memory import TTLCache


class Cache(Protocol):
    """Minimal cache contract shared by memory and persistent caches."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def clear(self) -> None: ...


__all__ = ["Cache", "TTLCache"]
