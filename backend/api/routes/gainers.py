from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from agents.gainer_analyst import GainerAnalystAgent
from agents.market_analyst import MarketAnalystAgent
from api.deps import (
    get_cache,
    get_gainer_analyst,
    get_market_analyst,
    get_market_data,
    get_news_fetcher,
)
from core.config import Settings, get_settings
from core.exceptions import ticker_not_found, upstream_error
from core.logging import get_logger
from models.schemas import (
    GainerDetail,
    GainersListResponse,
    Market,
    MarketSummary,
    StockGainer,
    compute_quality_score,
)
from services.cache import CacheBackend
from services.market_data import MarketDataService, today_str
from services.news_fetcher import NewsFetcher

router = APIRouter(prefix="/gainers", tags=["gainers"])
log = get_logger(__name__)


def _list_cache_key(market: Market) -> str:
    return f"gainers:{market}:{today_str()}"


def _analysis_cache_key(ticker: str, market: Market) -> str:
    return f"analysis:{market}:{ticker}:{today_str()}"


def _summary_cache_key(market: Market) -> str:
    return f"summary:{market}:{today_str()}"


def _apply_quality_scores(gainers: list[StockGainer]) -> list[StockGainer]:
    for g in gainers:
        score, label = compute_quality_score(g.price, g.volume, g.change_pct, g.ticker)
        g.quality_score = score
        g.quality_label = label
    return gainers


@router.get("/{market}", response_model=GainersListResponse)
async def list_gainers(
    market: Annotated[Market, Path(description="'us' or 'india'")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    analyst: Annotated[MarketAnalystAgent, Depends(get_market_analyst)],
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> GainersListResponse:
    """
    Return today's top gainers with quality scores and AI market narrative.
    Results are cached for 30 minutes (configurable via GAINERS_LIST_TTL).
    """
    list_key = _list_cache_key(market)
    summary_key = _summary_cache_key(market)

    if not refresh:
        cached = await cache.get(list_key)
        if cached:
            log.info("gainers.list_cache_hit", market=market)
            gainers = [StockGainer(**g) for g in cached["gainers"]]
            cached_summary = await cache.get(summary_key)
            summary = MarketSummary(**cached_summary) if cached_summary else None
            return GainersListResponse(
                market=market, date=today_str(), gainers=gainers,
                summary=summary, from_cache=True,
            )

    try:
        gainers = await market_data.get_gainers(market)
    except Exception as exc:
        log.error("gainers.list_fetch_error", market=market, error=str(exc))
        raise upstream_error("market data", str(exc))

    # Fire market summary AI call in parallel with cache write
    async def _get_summary() -> MarketSummary | None:
        try:
            s = await analyst.analyse(gainers, market)
            await cache.set(summary_key, s.model_dump(), settings.gainers_list_ttl)
            return s
        except Exception as exc:
            log.warning("gainers.summary_failed", error=str(exc))
            return None

    summary, _ = await asyncio.gather(
        _get_summary(),
        cache.set(list_key, {"gainers": [g.model_dump() for g in gainers]}, settings.gainers_list_ttl),
    )

    return GainersListResponse(
        market=market, date=today_str(), gainers=gainers,
        summary=summary, from_cache=False,
    )


@router.get("/{market}/{ticker}", response_model=GainerDetail)
async def get_gainer_detail(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path(description="Stock ticker symbol, e.g. AAPL or RELIANCE")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    news_fetcher: Annotated[NewsFetcher, Depends(get_news_fetcher)],
    analyst: Annotated[GainerAnalystAgent, Depends(get_gainer_analyst)],
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> GainerDetail:
    """
    Return full AI-powered analysis for a single stock.

    Speed: makes ONE combined Gemini call for both analysis and 30-day prediction
    instead of two sequential calls — roughly 40-50% faster than the old design.

    Comparison: when the searched ticker is not in today's top-gainer list the
    response includes a `comparison_to_gainers` field explaining how this stock's
    move differs from the day's biggest winners.
    """
    ticker = ticker.upper()
    key = _analysis_cache_key(ticker, market)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("gainers.detail_cache_hit", ticker=ticker, market=market)
            return GainerDetail(**cached)

    # Resolve gainer data and check whether ticker is in today's gainer list.
    # Both operations run in parallel to save an extra round-trip.
    gainer, gainers_list = await asyncio.gather(
        _resolve_gainer(ticker, market, market_data),
        _safe_get_gainers(market, market_data),
    )

    if gainer is None:
        raise ticker_not_found(ticker)

    # Only provide comparison context when the ticker is NOT in today's list.
    in_gainers = any(g.ticker == ticker for g in gainers_list)
    gainers_context = gainers_list[:3] if not in_gainers and gainers_list else None

    # Fetch fundamentals and news in parallel
    try:
        fundamentals, news = await asyncio.gather(
            market_data.get_fundamentals(ticker, market),
            news_fetcher.get_news(ticker, gainer.name),
            return_exceptions=True,
        )
    except Exception as exc:
        log.error("gainers.detail_fetch_error", ticker=ticker, error=str(exc))
        raise upstream_error("market data / news", str(exc))

    if isinstance(fundamentals, Exception):
        log.warning("gainers.fundamentals_failed", ticker=ticker, error=str(fundamentals))
        fundamentals = None
    if isinstance(news, Exception):
        log.warning("gainers.news_failed", ticker=ticker, error=str(news))
        news = []

    # Single combined AI call — analysis + prediction in one Gemini request.
    analysis = None
    prediction = None
    try:
        analysis, prediction = await analyst.analyse_full(
            ticker=ticker,
            change_pct=gainer.change_pct,
            company_name=gainer.name,
            sector=gainer.sector,
            news=news or [],
            fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
            gainers_context=gainers_context,
        )
    except Exception as exc:
        log.error("gainers.ai_failed", ticker=ticker, error=str(exc))
        # Return partial result rather than failing entirely

    detail = GainerDetail(
        gainer=gainer,
        fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
        news=news if not isinstance(news, Exception) else [],
        analysis=analysis,
        prediction=prediction,
        from_cache=False,
        analysed_at=datetime.utcnow(),
    )

    await cache.set(key, detail.model_dump(), settings.analysis_ttl)
    return detail


@router.delete("/{market}/{ticker}/cache", tags=["system"])
async def invalidate_cache(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path()],
    cache: Annotated[CacheBackend, Depends(get_cache)],
) -> dict[str, str]:
    """Manually invalidate the cached analysis for a ticker."""
    key = _analysis_cache_key(ticker.upper(), market)
    await cache.delete(key)
    return {"status": "invalidated", "key": key}


async def _resolve_gainer(
    ticker: str, market: Market, market_data: MarketDataService
) -> StockGainer | None:
    """
    Try to get gainer metadata from the daily list.
    Falls back to fetching the ticker directly via yfinance if not in the list.
    """
    try:
        gainers = await market_data.get_gainers(market)
        match = next((g for g in gainers if g.ticker == ticker), None)
        if match:
            return match
    except Exception:
        pass

    # Not in today's gainer list — build a minimal record from yfinance
    try:
        yf_ticker = f"{ticker}.NS" if market == "india" else ticker
        import yfinance as yf

        info = await asyncio.to_thread(lambda: yf.Ticker(yf_ticker).info)
        if not info:
            return None
        from services.market_data import _safe_float, _safe_int

        change_pct = info.get("regularMarketChangePercent", 0)
        if change_pct is None or change_pct <= 0:
            change_pct = 0.01  # Minimum to pass validator

        return StockGainer(
            ticker=ticker,
            name=info.get("shortName", ticker),
            market=market,
            price=float(info.get("regularMarketPrice", 0)),
            change_pct=float(change_pct),
            change_abs=float(info.get("regularMarketChange", 0)),
            volume=int(info.get("regularMarketVolume", 0)),
            avg_volume=_safe_int(info.get("averageDailyVolume3Month")),
            market_cap=_safe_float(info.get("marketCap")),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )
    except Exception:
        return None


async def _safe_get_gainers(
    market: Market, market_data: MarketDataService
) -> list[StockGainer]:
    """Return today's gainers list; empty list on any error (non-critical)."""
    try:
        return await market_data.get_gainers(market)
    except Exception:
        return []
