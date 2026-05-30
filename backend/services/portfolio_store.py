from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from models.portfolio import PortfolioEntry, PortfolioSummary, PortfolioStatus
from services.cache import CacheBackend
from core.logging import get_logger

log = get_logger(__name__)

_FOREVER = 60 * 60 * 24 * 365 * 10   # 10-year TTL (functionally permanent)
_INDEX_KEY = "portfolio:ids"


def _entry_key(id_: str) -> str:
    return f"portfolio:{id_}"


class PortfolioStore:
    """Persistent portfolio storage backed by CacheBackend (Redis or in-memory).

    Storage layout
    ──────────────
    portfolio:ids          → JSON list[str] of all entry IDs
    portfolio:{id}         → JSON dict serialised from PortfolioEntry.model_dump()

    Both keys use a 10-year TTL so they survive Redis restarts and never
    expire in practice.  Using a dedicated index key avoids needing Redis SCAN.
    """

    def __init__(self, cache: CacheBackend) -> None:
        self._cache = cache

    async def get_all(self) -> list[PortfolioEntry]:
        ids: list[str] = await self._cache.get(_INDEX_KEY) or []
        entries: list[PortfolioEntry] = []
        for id_ in ids:
            data = await self._cache.get(_entry_key(id_))
            if data:
                try:
                    entries.append(PortfolioEntry(**data))
                except Exception as exc:
                    log.warning("portfolio_store.deserialize_failed", id=id_, error=str(exc))
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    async def get(self, id_: str) -> Optional[PortfolioEntry]:
        data = await self._cache.get(_entry_key(id_))
        return PortfolioEntry(**data) if data else None

    async def save(self, entry: PortfolioEntry) -> None:
        await self._cache.set(_entry_key(entry.id), entry.model_dump(), _FOREVER)
        ids: list[str] = await self._cache.get(_INDEX_KEY) or []
        if entry.id not in ids:
            ids.append(entry.id)
            await self._cache.set(_INDEX_KEY, ids, _FOREVER)
        log.info("portfolio_store.saved", id=entry.id, ticker=entry.ticker)

    async def delete(self, id_: str) -> bool:
        data = await self._cache.get(_entry_key(id_))
        if not data:
            return False
        await self._cache.delete(_entry_key(id_))
        ids: list[str] = await self._cache.get(_INDEX_KEY) or []
        ids = [i for i in ids if i != id_]
        await self._cache.set(_INDEX_KEY, ids, _FOREVER)
        log.info("portfolio_store.deleted", id=id_)
        return True

    async def summary(self) -> PortfolioSummary:
        entries = await self.get_all()
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
