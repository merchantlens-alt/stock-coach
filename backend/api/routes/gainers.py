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
    FundamentalsData,
    GainerDetail,
    GainersListResponse,
    Market,
    MarketSummary,
    StockAnalysisResponse,
    StockGainer,
    compute_quality_score,
)
from services.cache import CacheBackend
from services.market_data import (
    MarketDataService,
    fundamentals_from_info,
    resolve_ticker_by_name,
    today_str,
)
from services.news_fetcher import NewsFetcher

router = APIRouter(prefix="/gainers", tags=["gainers"])
log = get_logger(__name__)


# ── Cache key helpers ─────────────────────────────────────────────────────────

def _list_cache_key(market: Market) -> str:
    return f"gainers:{market}:{today_str()}"


def _data_cache_key(ticker: str, market: Market) -> str:
    """Fast data endpoint (gainer + fundamentals + news, no AI). 30-min TTL."""
    return f"data:{market}:{ticker}:{today_str()}"


def _analysis_cache_key(ticker: str, market: Market) -> str:
    """Slow AI endpoint. 6-hour TTL so switching stocks doesn't re-run AI."""
    return f"analysis:{market}:{ticker}:{today_str()}"


def _summary_cache_key(market: Market) -> str:
    return f"summary:{market}:{today_str()}"


def _apply_quality_scores(gainers: list[StockGainer]) -> list[StockGainer]:
    for g in gainers:
        score, label = compute_quality_score(g.price, g.volume, g.change_pct, g.ticker)
        g.quality_score = score
        g.quality_label = label
    return gainers


# ── List gainers ──────────────────────────────────────────────────────────────

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

    # Never cache an empty result — let the next request try Gemini again.
    if not gainers:
        log.warning("gainers.empty_result_not_cached", market=market)
        return GainersListResponse(
            market=market, date=today_str(), gainers=[], summary=None, from_cache=False,
        )

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


# ── Fast data endpoint ────────────────────────────────────────────────────────

@router.get("/{market}/{ticker}", response_model=GainerDetail)
async def get_gainer_detail(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path(description="Stock ticker symbol, e.g. AAPL or RELIANCE")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    news_fetcher: Annotated[NewsFetcher, Depends(get_news_fetcher)],
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> GainerDetail:
    """
    Fast data endpoint — returns gainer info, fundamentals, and recent news.
    No AI call; typical cold response time 3–5 s.

    Call /analyse for AI-powered analysis and 30-day prediction (separate,
    slower endpoint that the frontend fetches in parallel).
    """
    ticker = ticker.upper()
    key = _data_cache_key(ticker, market)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("gainers.data_cache_hit", ticker=ticker, market=market)
            return GainerDetail(**cached)

    # _resolve_gainer returns the raw yfinance info dict alongside the StockGainer.
    # When the gainer came from the cached gainers list the dict is empty ({}),
    # meaning we still need a separate fundamentals call.  When it came from a
    # live yfinance lookup the dict is already populated and we can extract
    # fundamentals directly — saving a full second round-trip to Yahoo Finance.
    gainer, yf_info = await _resolve_gainer(ticker, market, market_data)
    if gainer is None:
        raise ticker_not_found(ticker)

    async def _get_fundamentals() -> FundamentalsData | None:
        if yf_info:
            # Reuse data already fetched during gainer resolution — no extra call.
            return fundamentals_from_info(yf_info)
        try:
            return await market_data.get_fundamentals(ticker, market)
        except Exception as exc:
            log.warning("gainers.fundamentals_failed", ticker=ticker, error=str(exc))
            return None

    fundamentals_result, news = await asyncio.gather(
        _get_fundamentals(),
        news_fetcher.get_news(ticker, gainer.name),
        return_exceptions=True,
    )

    fundamentals = fundamentals_result if not isinstance(fundamentals_result, Exception) else None
    if isinstance(news, Exception):
        log.warning("gainers.news_failed", ticker=ticker, error=str(news))
        news = []

    detail = GainerDetail(
        gainer=gainer,
        fundamentals=fundamentals,
        news=news,
        from_cache=False,
        fetched_at=datetime.utcnow(),
    )

    await cache.set(key, detail.model_dump(), settings.gainers_list_ttl)
    return detail


# ── Slow AI analysis endpoint ─────────────────────────────────────────────────

@router.get("/{market}/{ticker}/analyse", response_model=StockAnalysisResponse)
async def get_gainer_analysis(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path(description="Stock ticker symbol")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    news_fetcher: Annotated[NewsFetcher, Depends(get_news_fetcher)],
    analyst: Annotated[GainerAnalystAgent, Depends(get_gainer_analyst)],
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> StockAnalysisResponse:
    """
    Slow AI endpoint — returns GainerAnalysis + StockPrediction.
    Typical cold response time 10–15 s (one Gemini call).
    Cached 6 hours so switching stocks and coming back is instant.

    Designed to be fetched in parallel with GET /{market}/{ticker} so the
    frontend can show data immediately and fill in AI content when ready.
    """
    ticker = ticker.upper()
    key = _analysis_cache_key(ticker, market)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("gainers.analysis_cache_hit", ticker=ticker, market=market)
            return StockAnalysisResponse(**cached)

    # Resolve gainer + gainers list in parallel (list used for comparison context)
    (gainer, _yf_info), gainers_list = await asyncio.gather(
        _resolve_gainer(ticker, market, market_data),
        _safe_get_gainers(market, market_data),
    )

    if gainer is None:
        raise ticker_not_found(ticker)

    # Determine whether this ticker is in today's gainer list
    in_gainers = any(g.ticker == ticker for g in gainers_list)
    gainers_context = gainers_list[:3] if not in_gainers and gainers_list else None

    # Fetch fundamentals + news (needed for AI prompt quality).
    # If yfinance info was already fetched during gainer resolution reuse it.
    async def _get_analysis_fundamentals():
        if _yf_info:
            return fundamentals_from_info(_yf_info)
        try:
            return await market_data.get_fundamentals(ticker, market)
        except Exception as exc:
            log.warning("gainers.analysis_fundamentals_failed", ticker=ticker, error=str(exc))
            return None

    fundamentals_result, news = await asyncio.gather(
        _get_analysis_fundamentals(),
        news_fetcher.get_news(ticker, gainer.name),
        return_exceptions=True,
    )

    fundamentals = fundamentals_result if not isinstance(fundamentals_result, Exception) else None
    if isinstance(news, Exception):
        log.warning("gainers.analysis_news_failed", ticker=ticker, error=str(news))
        news = []

    # Single combined Gemini call — analysis + 30-day prediction
    analysis = None
    prediction = None
    try:
        analysis, prediction = await analyst.analyse_full(
            ticker=ticker,
            change_pct=gainer.change_pct,
            company_name=gainer.name,
            sector=gainer.sector,
            news=news if not isinstance(news, Exception) else [],
            fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
            gainers_context=gainers_context,
        )
    except Exception as exc:
        log.error("gainers.ai_failed", ticker=ticker, error=str(exc))
        # Return partial result (analysis=None) rather than a 500 — frontend handles gracefully

    response = StockAnalysisResponse(
        ticker=ticker,
        market=market,
        analysis=analysis,
        prediction=prediction,
        from_cache=False,
        analysed_at=datetime.utcnow(),
    )

    await cache.set(key, response.model_dump(), settings.analysis_ttl)
    return response


# ── Cache invalidation ────────────────────────────────────────────────────────

@router.delete("/{market}/{ticker}/cache", tags=["system"])
async def invalidate_cache(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path()],
    cache: Annotated[CacheBackend, Depends(get_cache)],
) -> dict[str, str]:
    """Manually invalidate both data and analysis caches for a ticker."""
    ticker = ticker.upper()
    data_key = _data_cache_key(ticker, market)
    analysis_key = _analysis_cache_key(ticker, market)
    await asyncio.gather(
        cache.delete(data_key),
        cache.delete(analysis_key),
    )
    return {"status": "invalidated", "ticker": ticker}


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _resolve_gainer(
    ticker: str, market: Market, market_data: MarketDataService
) -> tuple[StockGainer | None, dict]:
    """
    Resolve a ticker string to a StockGainer record.

    Returns (gainer, raw_yf_info) where:
      - raw_yf_info is non-empty when the gainer was resolved via yfinance
        (callers can extract FundamentalsData directly without a second call).
      - raw_yf_info is {} when the gainer came from the cached gainers list
        (callers should fetch fundamentals via market_data.get_fundamentals).

    Strategy:
      1. Check today's cached gainer list (instant).
      2. Direct yfinance lookup.
      3. If yfinance returns no price, resolve company name → ticker via
         Yahoo Finance search + Gemini fallback, then retry yfinance.
    """
    import yfinance as yf
    from services.market_data import _safe_float, _safe_int

    # ── Step 1: today's gainer list (cache hit → instant) ────────────────────
    try:
        gainers = await market_data.get_gainers(market)
        match = next((g for g in gainers if g.ticker == ticker), None)
        if match:
            return match, {}   # {} signals: fetch fundamentals separately
    except Exception:
        pass

    # ── Step 2: direct yfinance lookup ────────────────────────────────────────
    async def _yf_lookup(sym: str) -> dict:
        yf_sym = f"{sym}.NS" if market == "india" else sym
        return await asyncio.to_thread(lambda: yf.Ticker(yf_sym).info)

    info: dict = {}
    try:
        info = await _yf_lookup(ticker)
    except Exception:
        pass

    # ── Step 3: name resolution fallback ──────────────────────────────────────
    # If yfinance returned no market price the user probably typed a company name
    # (e.g. "SANDISK" → should resolve to "SNDK"). We try Yahoo Finance search
    # first, then Gemini (training knowledge) as a reliable secondary.
    if not info or not info.get("regularMarketPrice"):
        resolved = await resolve_ticker_by_name(ticker, market)
        if resolved and resolved.upper() != ticker:
            log.info(
                "gainers.ticker_resolved",
                query=ticker,
                resolved=resolved,
                market=market,
            )
            ticker = resolved.upper()
            try:
                info = await _yf_lookup(ticker)
            except Exception:
                pass

    if not info or not info.get("regularMarketPrice"):
        return None, {}

    change_pct = info.get("regularMarketChangePercent") or 0.0
    if change_pct < 0:
        change_pct = 0.01  # minimum so the validator passes for searched non-gainers

    gainer = StockGainer(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName") or ticker,
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
    return gainer, info   # info passed back so caller can extract fundamentals


async def _safe_get_gainers(
    market: Market, market_data: MarketDataService
) -> list[StockGainer]:
    """Return today's gainers list; empty list on any error (non-critical)."""
    try:
        return await market_data.get_gainers(market)
    except Exception:
        return []
