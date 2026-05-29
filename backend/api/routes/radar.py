"""
Radar route — GET /api/radar/{market}

Reads today's business headlines, runs a single Gemini call, and returns up to
5 structural catalyst themes that could move specific stocks in the next 5-30 days.

Cache TTL: 12 h.  Refreshes at market open and midday; weekend news is still fresh.
Cost: ~$0.0004 per cold call × 2 calls/day = ~$0.0003/day.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends

from agents.radar_analyst import RadarAnalystAgent
from api.deps import get_cache, get_news_fetcher, get_radar_analyst
from core.config import Settings, get_settings
from core.logging import get_logger
from models.schemas import Market, RadarResponse
from services.cache import CacheBackend
from services.news_fetcher import NewsFetcher

router = APIRouter(prefix="/radar", tags=["radar"])
log = get_logger(__name__)

_RADAR_TTL = 12 * 3600  # 12 h


def _radar_cache_key(market: Market) -> str:
    return f"radar:{market}"


@router.get("/{market}", response_model=RadarResponse, summary="Emerging catalyst radar")
async def get_radar(
    market: Market,
    cache: CacheBackend = Depends(get_cache),
    news_fetcher: NewsFetcher = Depends(get_news_fetcher),
    radar_analyst: RadarAnalystAgent = Depends(get_radar_analyst),
    settings: Settings = Depends(get_settings),
) -> RadarResponse:
    """
    Returns up to 5 structural catalyst themes identified from today's financial news.
    Focuses on stocks that haven't moved yet but are positioned to benefit.
    Cached 12 h — call is cheap and rarely needs to be fresh more than twice a day.
    """
    key = _radar_cache_key(market)

    # ── Cache hit ──────────────────────────────────────────────────────────────
    cached = await cache.get(key)
    if cached:
        log.info("radar.cache_hit", market=market)
        return RadarResponse(**{**cached, "from_cache": True})

    # ── Cold path: fetch news → AI scan ───────────────────────────────────────
    log.info("radar.cold_fetch_start", market=market)
    news = await news_fetcher.get_market_news(market, limit=25)

    if not news:
        log.warning("radar.no_news", market=market)
        return RadarResponse(
            market=market,
            signals=[],
            no_signals_reason="No news available at this time. Please try again later.",
            from_cache=False,
        )

    signals, no_reason = await radar_analyst.scan(news, market)

    response = RadarResponse(
        market=market,
        signals=signals,
        no_signals_reason=no_reason,
        from_cache=False,
        generated_at=datetime.utcnow(),
    )

    # Only cache if we got a real response (don't cache empty results from transient failures)
    if signals or no_reason:
        await cache.set(key, response.model_dump(), _RADAR_TTL)
        log.info("radar.cached", market=market, signals=len(signals), ttl=_RADAR_TTL)

    return response
