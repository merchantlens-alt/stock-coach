"""
Value Recovery Scanner route — GET /api/recovery/{market}

Returns stocks where valuation is compressed relative to fundamentals and
multiple inflection signals suggest a fundamental re-rating is in progress.
These are different from dips (price-driven) — they're fundamental recoveries
where the market hasn't yet repriced improving earnings / margins / ROE.

Cache TTL: 2 hours — fundamental metrics change daily at best.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_value_recovery_scanner
from core.logging import get_logger
from models.schemas import Market, ValueRecoveryScanResponse
from services.cache import CacheBackend
from services.value_recovery_scanner import ValueRecoveryScannerService

router = APIRouter(prefix="/recovery", tags=["recovery"])
log = get_logger(__name__)

_RECOVERY_TTL = 2 * 60 * 60  # 2 hours


def _cache_key(market: Market) -> str:
    return f"recovery:{market}"


@router.get("/{market}", response_model=ValueRecoveryScanResponse)
async def get_value_recovery(
    market: Market,
    cache: Annotated[CacheBackend, Depends(get_cache)],
    scanner: Annotated[ValueRecoveryScannerService, Depends(get_value_recovery_scanner)],
    refresh: bool = False,
) -> ValueRecoveryScanResponse:
    """
    Returns value recovery candidates — stocks with compressed valuations and
    multiple fundamental inflection signals suggesting a re-rating is in progress.

    **What makes a value recovery:**
    - P/E below market median (< 22×) OR forward P/E contracting meaningfully
    - At least 2 active inflection signals: EPS growing, revenue growing,
      P/E contracting, strong ROE (>13%), low debt (<0.8×), profitable (margin >8%),
      or analyst consensus Buy/Outperform
    - Not loss-making (profit margin > -10%)
    - Not analyst-rated Sell / Underperform

    **Different from Dips scanner:**
    Dips = stock fell 8-45% from price high (price-driven, technical signal).
    Recovery = valuation compressed + fundamentals improving (fundamental signal,
    usually a 2-8 week re-rating play rather than a bounce trade).

    Cached 2 hours per market. Pass `?refresh=true` to bust the cache.
    """
    key = _cache_key(market)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("recovery.cache_hit", market=market)
            return ValueRecoveryScanResponse(**{**cached, "from_cache": True})
    else:
        log.info("recovery.cache_bust", market=market)

    log.info("recovery.cold_scan_start", market=market)
    response = await scanner.scan(market)
    response.scanned_at = datetime.utcnow()

    if response.stocks:
        await cache.set(key, response.model_dump(), _RECOVERY_TTL)
        log.info(
            "recovery.cached",
            market=market,
            count=len(response.stocks),
            ttl=_RECOVERY_TTL,
        )

    return response
