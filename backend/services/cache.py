from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import redis.asyncio as aioredis

from core.logging import get_logger

log = get_logger(__name__)


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def ping(self) -> bool: ...


@dataclass
class _Entry:
    value: Any
    expires_at: float


class InMemoryCache(CacheBackend):
    """TTL-aware in-memory cache. Not suitable for multi-process deployments."""

    def __init__(self) -> None:
        self._store: dict[str, _Entry] = {}

    async def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def ping(self) -> bool:
        return True


class RedisCache(CacheBackend):
    def __init__(self, url: str) -> None:
        self._client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[Any]:
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            log.warning("redis.get_failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            log.warning("redis.set_failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:
            log.warning("redis.delete_failed", key=key, error=str(exc))

    async def ping(self) -> bool:
        try:
            return await self._client.ping()
        except Exception:
            return False


def build_cache(redis_url: str) -> CacheBackend:
    if redis_url:
        log.info("cache.using_redis", url=redis_url)
        return RedisCache(redis_url)
    log.info("cache.using_memory")
    return InMemoryCache()
