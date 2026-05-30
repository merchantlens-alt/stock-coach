"""
GET /api/gainers/{market}/{ticker}/growth-triggers

Returns an institutional-style Growth Triggers research note.
24-hour cache — this is a research document, not real-time data.
Cold call: ~15-25 s (Google Search grounding + Gemini).
"""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from agents.growth_triggers_agent import GrowthTriggersAgent
from api.deps import (
    get_cache,
    get_growth_triggers_agent,
    get_market_data,
    get_news_fetcher,
    get_quarterly_fetcher,
)
from core.config import get_settings, Settings
from core.exceptions import ticker_not_found
from core.logging import get_logger
from models.schemas import GrowthTriggersReport, Market
from services.cache import CacheBackend
from services.market_data import MarketDataService, fundamentals_from_info
from services.news_fetcher import NewsFetcher
from services.quarterly_fetcher import QuarterlyFetcher, format_for_prompt as fmt_quarterly

router = APIRouter(prefix="/gainers", tags=["growth_triggers"])
log = get_logger(__name__)

_CACHE_TTL = 24 * 3600   # 24 hours — research note, not real-time


def _cache_key(ticker: str, market: Market) -> str:
    return f"growth-triggers:{market}:{ticker}"


@router.get("/{market}/{ticker}/growth-triggers", response_model=GrowthTriggersReport)
async def get_growth_triggers(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path(description="Stock ticker symbol, e.g. AAPL or RELIANCE")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    news_fetcher: Annotated[NewsFetcher, Depends(get_news_fetcher)],
    quarterly_fetcher: Annotated[QuarterlyFetcher, Depends(get_quarterly_fetcher)],
    agent: Annotated[GrowthTriggersAgent, Depends(get_growth_triggers_agent)],
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> GrowthTriggersReport:
    """
    Growth Triggers research note — 3-5 specific business growth levers with
    P&L timelines, conviction tags, and an investment scorecard.

    Cold path: Google Search grounding + Gemini (~15-25 s).
    Cached 24 hours.
    """
    ticker = ticker.upper()
    key = _cache_key(ticker, market)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("growth_triggers.cache_hit", ticker=ticker, market=market)
            return GrowthTriggersReport(**{**cached, "from_cache": True})

    # ── Resolve the gainer to get name + price ────────────────────────────────
    # Re-use the gainers cache if it exists — avoids a redundant yfinance call.
    from api.routes.gainers import _resolve_gainer  # lazy import to avoid circular

    gainer, yf_info = await _resolve_gainer(ticker, market, market_data, cache)
    if gainer is None:
        raise ticker_not_found(ticker)

    resolved_ticker = gainer.ticker

    # ── Fetch fundamentals, news, quarterly data in parallel ──────────────────
    async def _get_fundamentals():
        if yf_info:
            return fundamentals_from_info(yf_info)
        try:
            return await market_data.get_fundamentals(resolved_ticker, market)
        except Exception as exc:
            log.warning("growth_triggers.fundamentals_failed", ticker=resolved_ticker, error=str(exc))
            return None

    async def _get_quarterly() -> "str | None":
        from models.schemas import QuarterlySnapshot
        try:
            snap = await quarterly_fetcher.fetch(resolved_ticker, market)
            if snap:
                return fmt_quarterly(snap)
        except Exception as exc:
            log.warning("growth_triggers.quarterly_failed", ticker=resolved_ticker, error=str(exc))
        return None

    fundamentals_result, news_result, quarterly_text = await asyncio.gather(
        _get_fundamentals(),
        news_fetcher.get_news(resolved_ticker, gainer.name, market=market),
        _get_quarterly(),
        return_exceptions=True,
    )

    fundamentals = fundamentals_result if not isinstance(fundamentals_result, Exception) else None
    news = news_result if not isinstance(news_result, Exception) else []
    quarterly_str = quarterly_text if not isinstance(quarterly_text, Exception) else None

    news_headlines = [item.title for item in (news or [])]

    # ── Call the AI agent ────────────────────────────────────────────────────
    report = await agent.generate(
        ticker=resolved_ticker,
        name=gainer.name,
        market=market,
        price=gainer.price,
        fundamentals=fundamentals,
        news_headlines=news_headlines,
        quarterly_summary=quarterly_str,
    )

    # ── Cache for 24 h ────────────────────────────────────────────────────────
    await cache.set(key, report.model_dump(), _CACHE_TTL)
    log.info(
        "growth_triggers.generated",
        ticker=resolved_ticker,
        market=market,
        triggers=len(report.triggers),
    )
    return report
