"""
Dip Scanner route — GET /api/dips/{market}

Returns stocks that have pulled back 8-45% from their 3-month high but whose
fundamentals (analyst consensus BUY, revenue growth, RSI oversold) suggest the
decline is technical/macro, not a fundamental deterioration.

Cache TTL: 60 min — dip opportunities shift slowly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_dip_scanner
from core.logging import get_logger
from models.schemas import DipScanResponse, Market
from services.cache import CacheBackend
from services.dip_scanner import DipScannerService

router = APIRouter(prefix="/dips", tags=["dips"])
log = get_logger(__name__)

_DIP_TTL = 60 * 60  # 1 hour


def _cache_key(market: Market) -> str:
    return f"dips:{market}"


@router.get("/{market}", response_model=DipScanResponse)
async def get_dip_scan(
    market: Market,
    cache: Annotated[CacheBackend, Depends(get_cache)],
    scanner: Annotated[DipScannerService, Depends(get_dip_scanner)],
) -> DipScanResponse:
    """
    Returns quality dip-buy candidates — stocks that are technically oversold
    but fundamentally sound. Sorted by dip_score (prime > watch).

    **What makes a quality dip:**
    - Down 8–45% from 3-month high (meaningful pullback, not a collapse)
    - RSI approaching oversold (<45)
    - Analyst consensus BUY with meaningful upside to price target
    - Revenue growing year-over-year
    - No analyst downgrade / sell rating

    Cached 1 hour per market.
    """
    key = _cache_key(market)

    cached = await cache.get(key)
    if cached:
        log.info("dips.cache_hit", market=market)
        return DipScanResponse(**{**cached, "from_cache": True})

    log.info("dips.cold_scan_start", market=market)
    response = await scanner.scan(market)
    response.scanned_at = datetime.utcnow()

    if response.dips:
        await cache.set(key, response.model_dump(), _DIP_TTL)
        log.info("dips.cached", market=market, count=len(response.dips), ttl=_DIP_TTL)

    return response
