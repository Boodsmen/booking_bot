"""Простой in-memory TTL-кеш для списков оборудования и категорий."""

import time
from typing import Any


class TTLCache:
    """TTL-кеш на основе dict + временных меток."""

    def __init__(self, default_ttl: int = 300):
        """default_ttl: время жизни записи в секундах (по умолчанию 5 мин)."""
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Получить значение по ключу, если оно не истекло."""
        if key not in self._store:
            return None

        value, expires_at = self._store[key]
        if time.monotonic() > expires_at:
            del self._store[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Сохранить значение с временем жизни."""
        if ttl is None:
            ttl = self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        """Удалить ключ из кеша."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Очистить весь кеш."""
        self._store.clear()


equipment_cache = TTLCache(default_ttl=300)
