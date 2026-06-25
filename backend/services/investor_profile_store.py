from __future__ import annotations

from typing import Optional

from models.schemas import InvestorProfile
from services.cache import CacheBackend
from core.logging import get_logger

log = get_logger(__name__)

_FOREVER = 60 * 60 * 24 * 365 * 10   # 10-year TTL


def _profile_key(user_id: str) -> str:
    return f"user:{user_id}:investor_profile"


class InvestorProfileStore:
    """User-scoped profile store backed by CacheBackend (Redis or in-memory)."""

    def __init__(self, cache: CacheBackend) -> None:
        self._cache = cache

    async def get(self, user_id: str) -> Optional[InvestorProfile]:
        data = await self._cache.get(_profile_key(user_id))
        if not data:
            return None
        try:
            return InvestorProfile(**data)
        except Exception as exc:
            log.warning("investor_profile_store.deserialize_failed", error=str(exc))
            return None

    async def save(self, profile: InvestorProfile, user_id: str) -> None:
        await self._cache.set(_profile_key(user_id), profile.model_dump(), _FOREVER)
        log.info("investor_profile_store.saved", horizon_years=profile.horizon_years, user_id=user_id)

    async def delete(self, user_id: str) -> None:
        await self._cache.delete(_profile_key(user_id))
        log.info("investor_profile_store.deleted", user_id=user_id)
