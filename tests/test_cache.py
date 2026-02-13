"""Tests for TTL cache."""

import time
import pytest

from utils.cache import TTLCache


def test_cache_set_and_get():
    """Test basic set and get."""
    cache = TTLCache(default_ttl=60)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_get_missing_key():
    """Test getting a nonexistent key."""
    cache = TTLCache(default_ttl=60)
    assert cache.get("nonexistent") is None


def test_cache_expiration():
    """Test that expired items return None."""
    cache = TTLCache(default_ttl=1)
    cache.set("key1", "value1", ttl=0)  # Already expired (0 seconds TTL)
    # The item was stored with expires_at = monotonic() + 0, which is already past
    time.sleep(0.01)
    assert cache.get("key1") is None


def test_cache_custom_ttl():
    """Test that custom TTL is respected."""
    cache = TTLCache(default_ttl=60)
    cache.set("short", "val", ttl=0)
    time.sleep(0.01)
    assert cache.get("short") is None

    cache.set("long", "val", ttl=300)
    assert cache.get("long") == "val"


def test_cache_invalidate():
    """Test manual invalidation."""
    cache = TTLCache(default_ttl=60)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    cache.invalidate("key1")
    assert cache.get("key1") is None


def test_cache_invalidate_nonexistent():
    """Test that invalidating nonexistent key doesn't raise."""
    cache = TTLCache(default_ttl=60)
    cache.invalidate("nonexistent")  # Should not raise


def test_cache_clear():
    """Test clearing entire cache."""
    cache = TTLCache(default_ttl=60)
    cache.set("key1", "val1")
    cache.set("key2", "val2")
    cache.set("key3", "val3")

    cache.clear()

    assert cache.get("key1") is None
    assert cache.get("key2") is None
    assert cache.get("key3") is None


def test_cache_overwrite():
    """Test overwriting existing key."""
    cache = TTLCache(default_ttl=60)
    cache.set("key1", "old_value")
    cache.set("key1", "new_value")
    assert cache.get("key1") == "new_value"


def test_cache_different_types():
    """Test caching different value types."""
    cache = TTLCache(default_ttl=60)
    cache.set("string", "hello")
    cache.set("int", 42)
    cache.set("list", [1, 2, 3])
    cache.set("dict", {"a": 1})

    assert cache.get("string") == "hello"
    assert cache.get("int") == 42
    assert cache.get("list") == [1, 2, 3]
    assert cache.get("dict") == {"a": 1}
