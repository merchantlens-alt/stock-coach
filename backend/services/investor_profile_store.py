from __future__ import annotations

from typing import Optional

from models.schemas import InvestorProfile
from services.cache import CacheBackend
from core.logging import get_logger

log = get_logger(__name__)

_PROFILE_KEY = "investor_profile"
_FOREVER = 60 * 60 * 24 * 365 * 10   # 10-year TTL


class InvestorProfileStore:
    """Single-profile store backed by CacheBackend (Redis or in-memory).

    Layout: one key ``investor_profile`` holds the serialised InvestorProfile.
    """

    def __init__(self, cache: CacheBackend) -> None:
        self._cache = cache

    async def get(self) -> Optional[InvestorProfile]:
        data = await self._cache.get(_PROFILE_KEY)
        if not data:
            return None
        try:
            return InvestorProfile(**data)
        except Exception as exc:
            log.warning("investor_profile_store.deserialize_failed", error=str(exc))
            return None

    async def save(self, profile: InvestorProfile) -> None:
        await self._cache.set(_PROFILE_KEY, profile.model_dump(), _FOREVER)
        log.info("investor_profile_store.saved", horizon_years=profile.horizon_years)

    async def delete(self) -> None:
        await self._cache.delete(_PROFILE_KEY)
        log.info("investor_profile_store.deleted")
