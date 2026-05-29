"""
Catalyst Scanner route — GET /api/catalyst/{market}

Finds the top-moving stocks with confirmed news catalysts, ranked by a composite
momentum score (volume ratio × price change × catalyst bonus).

Cache TTL: 30 min — shorter than the gainers list because the scanner is designed
to show what's moving RIGHT NOW. A 2-hour cache would miss intra-day moves.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_catalyst_scanner
from core.config import Settings, get_settings
from core.logging import get_logger
from models.schemas import CatalystScanResponse, Market
from services.cache import CacheBackend
from services.catalyst_scanner import CatalystScannerService

router = APIRouter(prefix="/catalyst", tags=["catalyst"])
log = get_logger(__name__)

_CATALYST_TTL = 30 * 60  # 30 minutes


def _cache_key(market: Market) -> str:
    return f"catalyst:{market}"


@router.get(
    "/{market}",
    response_model=CatalystScanResponse,
    summary="Catalyst Scanner — top movers with confirmed news catalysts",
)
async def get_catalyst_scan(
    market: Market,
    cache: CacheBackend = Depends(get_cache),
    scanner: CatalystScannerService = Depends(get_catalyst_scanner),
    settings: Settings = Depends(get_settings),
) -> CatalystScanResponse:
    """
    Returns up to 15 stocks that are moving significantly today with a confirmed
    news catalyst, ranked by momentum score (0-100).

    **Momentum score breakdown:**
    - Volume ratio (0-40 pts): how much more than average today's volume is
    - Price change (0-40 pts): magnitude of the move
    - Catalyst bonus (20 pts): confirmed news event (earnings, FDA, contract, etc.)

    **Signal tiers:**
    - `strong_move` (score ≥ 60): high-conviction, volume + catalyst confirmed
    - `emerging` (score 30-59): developing move, watch closely
    - `noise` (score < 30): low-conviction, momentum only

    Cached 30 minutes per market.
    """
    key = _cache_key(market)

    # ── Cache hit ──────────────────────────────────────────────────────────────
    cached = await cache.get(key)
    if cached:
        log.info("catalyst.cache_hit", market=market)
        return CatalystScanResponse(**{**cached, "from_cache": True})

    # ── Cold path ──────────────────────────────────────────────────────────────
    log.info("catalyst.cold_scan_start", market=market)
    response = await scanner.scan(market)
    response.scanned_at = datetime.utcnow()

    if response.plays:
        await cache.set(key, response.model_dump(), _CATALYST_TTL)
        log.info(
            "catalyst.cached",
            market=market,
            plays=len(response.plays),
            ttl=_CATALYST_TTL,
        )

    return response
