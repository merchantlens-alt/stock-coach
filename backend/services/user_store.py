"""User account storage backed by CacheBackend (Redis or in-memory).

Layout
──────
users:by_username:{username}  →  {user_id, username, hashed_password}
users:by_id:{user_id}         →  {user_id, username, hashed_password}
"""
from __future__ import annotations

import uuid
from typing import Optional

from core.logging import get_logger
from services.cache import CacheBackend

log = get_logger(__name__)

_FOREVER = 60 * 60 * 24 * 365 * 10   # 10-year TTL


def _by_username_key(username: str) -> str:
    return f"users:by_username:{username.lower()}"


def _by_id_key(user_id: str) -> str:
    return f"users:by_id:{user_id}"


class UserStore:
    def __init__(self, cache: CacheBackend) -> None:
        self._cache = cache

    async def get_by_username(self, username: str) -> Optional[dict]:
        return await self._cache.get(_by_username_key(username))

    async def get_by_id(self, user_id: str) -> Optional[dict]:
        return await self._cache.get(_by_id_key(user_id))

    async def create(self, username: str, hashed_password: str) -> dict:
        user_id = str(uuid.uuid4())
        record = {"user_id": user_id, "username": username, "hashed_password": hashed_password}
        await self._cache.set(_by_username_key(username), record, _FOREVER)
        await self._cache.set(_by_id_key(user_id), record, _FOREVER)
        log.info("user_store.created", username=username, user_id=user_id)
        return record

    async def exists(self, username: str) -> bool:
        return bool(await self._cache.get(_by_username_key(username)))
