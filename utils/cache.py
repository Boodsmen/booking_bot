"""Simple in-memory TTL cache for equipment and category lists."""

import time
from typing import Any


class TTLCache:
    """Thread-safe TTL cache using dict + timestamps."""

    def __init__(self, default_ttl: int = 300):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (default: 5 min)
        """
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """
        Get value by key if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if missing/expired
        """
        if key not in self._store:
            return None

        value, expires_at = self._store[key]
        if time.monotonic() > expires_at:
            del self._store[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Set value with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        if ttl is None:
            ttl = self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        """
        Remove key from cache.

        Args:
            key: Cache key to remove
        """
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear entire cache."""
        self._store.clear()


# Singleton cache instance
equipment_cache = TTLCache(default_ttl=300)
