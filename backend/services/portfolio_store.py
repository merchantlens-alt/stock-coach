from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from models.portfolio import PortfolioEntry, PortfolioSummary, PortfolioStatus
from services.cache import CacheBackend
from core.logging import get_logger

log = get_logger(__name__)

_FOREVER = 60 * 60 * 24 * 365 * 10   # 10-year TTL


def _index_key(user_id: str) -> str:
    return f"user:{user_id}:portfolio:ids"


def _entry_key(user_id: str, id_: str) -> str:
    return f"user:{user_id}:portfolio:{id_}"


class PortfolioStore:
    """User-scoped portfolio storage backed by CacheBackend (Redis or in-memory).

    Storage layout
    ──────────────
    user:{user_id}:portfolio:ids      → JSON list[str] of all entry IDs
    user:{user_id}:portfolio:{id}     → JSON dict serialised from PortfolioEntry.model_dump()
    """

    def __init__(self, cache: CacheBackend) -> None:
        self._cache = cache

    async def get_all(self, user_id: str) -> list[PortfolioEntry]:
        ids: list[str] = await self._cache.get(_index_key(user_id)) or []
        entries: list[PortfolioEntry] = []
        for id_ in ids:
            data = await self._cache.get(_entry_key(user_id, id_))
            if data:
                try:
                    entries.append(PortfolioEntry(**data))
                except Exception as exc:
                    log.warning("portfolio_store.deserialize_failed", id=id_, error=str(exc))
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    async def get(self, user_id: str, id_: str) -> Optional[PortfolioEntry]:
        data = await self._cache.get(_entry_key(user_id, id_))
        return PortfolioEntry(**data) if data else None

    async def save(self, entry: PortfolioEntry, user_id: str) -> None:
        await self._cache.set(_entry_key(user_id, entry.id), entry.model_dump(), _FOREVER)
        ids: list[str] = await self._cache.get(_index_key(user_id)) or []
        if entry.id not in ids:
            ids.append(entry.id)
            await self._cache.set(_index_key(user_id), ids, _FOREVER)
        log.info("portfolio_store.saved", id=entry.id, ticker=entry.ticker, user_id=user_id)

    async def delete(self, user_id: str, id_: str) -> bool:
        data = await self._cache.get(_entry_key(user_id, id_))
        if not data:
            return False
        await self._cache.delete(_entry_key(user_id, id_))
        ids: list[str] = await self._cache.get(_index_key(user_id)) or []
        ids = [i for i in ids if i != id_]
        await self._cache.set(_index_key(user_id), ids, _FOREVER)
        log.info("portfolio_store.deleted", id=id_, user_id=user_id)
        return True

    async def summary(self, user_id: str) -> PortfolioSummary:
        entries = await self.get_all(user_id)
        resolved = [e for e in entries if e.status in (PortfolioStatus.win, PortfolioStatus.loss)]
        wins = sum(1 for e in resolved if e.status == PortfolioStatus.win)
        losses = sum(1 for e in resolved if e.status == PortfolioStatus.loss)
        win_rate = round(wins / len(resolved), 3) if resolved else None
        return PortfolioSummary(
            entries=entries,
            total_active=sum(1 for e in entries if e.status == PortfolioStatus.active),
            total_resolved=len(resolved),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
        )
