"""
Catalyst Scanner route — GET /api/catalyst/{market}

Finds the top-moving stocks with confirmed news catalysts, ranked by a composite
momentum score (volume ratio × price change × catalyst bonus).

Cache TTL: 30 min — shorter than the gainers list because the scanner is designed
to show what's moving RIGHT NOW. A 2-hour cache would miss intra-day moves.

Prediction enrichment: after building the scan, each play is enriched with the
cached 30-day AI prediction (if the stock has been analysed). This lets the UI
flag contradictions: a stock with a 100 momentum score and a -10% AI prediction
is a "likely reversal" — very different from a 100-score stock with +15% outlook.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_catalyst_scanner
from core.config import Settings, get_settings
from core.logging import get_logger
from models.schemas import CatalystPlay, CatalystScanResponse, Market
from services.cache import CacheBackend
from services.catalyst_scanner import CatalystScannerService

router = APIRouter(prefix="/catalyst", tags=["catalyst"])
log = get_logger(__name__)

_CATALYST_TTL = 30 * 60  # 30 minutes


def _cache_key(market: Market) -> str:
    return f"catalyst:{market}"


def _analysis_key(market: Market, ticker: str) -> str:
    return f"analysis:{market}:{ticker}"


async def _enrich_with_predictions(
    plays: list[CatalystPlay],
    market: Market,
    cache: CacheBackend,
) -> list[CatalystPlay]:
    """
    Batch-read the analysis cache for every play and inject ai_prediction_pct /
    ai_prediction_confidence.  Completely non-blocking: missing or failed reads
    are silently skipped — plays without cached analysis are returned unchanged.
    """
    keys = [_analysis_key(market, p.ticker) for p in plays]
    results = await asyncio.gather(*[cache.get(k) for k in keys], return_exceptions=True)

    enriched: list[CatalystPlay] = []
    for play, result in zip(plays, results):
        if isinstance(result, dict):
            prediction: dict[str, Any] = result.get("prediction") or {}
            pct  = prediction.get("predicted_change_pct")
            conf = prediction.get("confidence")
            if pct is not None:
                play = play.model_copy(update={
                    "ai_prediction_pct": round(float(pct), 1),
                    "ai_prediction_confidence": round(float(conf), 2) if conf is not None else None,
                })
        enriched.append(play)
    return enriched


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
    Plays are enriched with cached 30-day AI predictions where available.
    """
    key = _cache_key(market)

    # ── Cache hit — still enrich with latest predictions ──────────────────────
    # The scan result is cached for 30 min, but prediction cache is updated
    # separately. Re-read predictions on every request so the UI always shows
    # the latest AI outlook even when the scan itself is cached.
    cached = await cache.get(key)
    if cached:
        log.info("catalyst.cache_hit", market=market)
        response = CatalystScanResponse(**{**cached, "from_cache": True})
        response.plays = await _enrich_with_predictions(response.plays, market, cache)
        return response

    # ── Cold path ──────────────────────────────────────────────────────────────
    log.info("catalyst.cold_scan_start", market=market)
    response = await scanner.scan(market)
    response.scanned_at = datetime.utcnow()

    if response.plays:
        # Cache the raw scan (without predictions — those change independently)
        await cache.set(key, response.model_dump(), _CATALYST_TTL)
        log.info(
            "catalyst.cached",
            market=market,
            plays=len(response.plays),
            ttl=_CATALYST_TTL,
        )
        # Enrich with predictions after caching so the cache stays prediction-free
        # (predictions have their own cache lifetime)
        response.plays = await _enrich_with_predictions(response.plays, market, cache)

    return response
