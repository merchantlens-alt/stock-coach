from __future__ import annotations

import asyncio

import pytest

from services.cache import InMemoryCache


class TestInMemoryCache:
    async def test_set_and_get(self) -> None:
        cache = InMemoryCache()
        await cache.set("key1", {"data": 42}, ttl=60)
        result = await cache.get("key1")
        assert result == {"data": 42}

    async def test_missing_key_returns_none(self) -> None:
        cache = InMemoryCache()
        result = await cache.get("nonexistent")
        assert result is None

    async def test_expired_key_returns_none(self) -> None:
        cache = InMemoryCache()
        await cache.set("key", "value", ttl=1)
        # Manually expire by manipulating the entry
        cache._store["key"].expires_at = 0.0
        result = await cache.get("key")
        assert result is None

    async def test_delete_removes_key(self) -> None:
        cache = InMemoryCache()
        await cache.set("key", "value", ttl=60)
        await cache.delete("key")
        assert await cache.get("key") is None

    async def test_delete_nonexistent_key_is_safe(self) -> None:
        cache = InMemoryCache()
        await cache.delete("does_not_exist")  # Should not raise

    async def test_overwrite_existing_key(self) -> None:
        cache = InMemoryCache()
        await cache.set("key", "first", ttl=60)
        await cache.set("key", "second", ttl=60)
        assert await cache.get("key") == "second"

    async def test_ping_returns_true(self) -> None:
        cache = InMemoryCache()
        assert await cache.ping() is True
