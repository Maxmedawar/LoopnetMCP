"""In-memory TTL cache for Loopnet responses."""

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 500):
        self._store: dict[str, tuple[float, int, Any]] = {}
        self._ttl = ttl_seconds
        self._max = max_entries

    def get(self, key: str) -> Any | None:
        if key in self._store:
            timestamp, ttl_seconds, value = self._store[key]
            if time.time() - timestamp < ttl_seconds:
                return value
            del self._store[key]
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        if len(self._store) >= self._max and key not in self._store:
            self._evict_oldest()
        self._store[key] = (time.time(), ttl_seconds or self._ttl, value)

    def clear(self) -> None:
        self._store.clear()

    def _evict_oldest(self) -> None:
        if not self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k][0])
        del self._store[oldest_key]

    def __len__(self) -> int:
        return len(self._store)
