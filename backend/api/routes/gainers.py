from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query

from agents.gainer_analyst import GainerAnalystAgent
from agents.market_analyst import MarketAnalystAgent
from api.deps import (
    get_cache,
    get_gainer_analyst,
    get_market_analyst,
    get_market_data,
    get_news_fetcher,
    get_quarterly_fetcher,
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
    Period,
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
from services.quarterly_fetcher import QuarterlyFetcher, format_for_prompt as fmt_quarterly

router = APIRouter(prefix="/gainers", tags=["gainers"])
log = get_logger(__name__)


# ── Prediction enrichment ─────────────────────────────────────────────────────

async def _enrich_with_predictions(
    gainers: list[StockGainer],
    market: Market,
    cache: CacheBackend,
) -> list[StockGainer]:
    """
    Batch-read the analysis cache for every gainer and inject cached
    prediction data (predicted_change_pct, confidence) into each StockGainer.

    This is a read-only enrichment — prediction data is never written to the
    gainers list cache, so the two caches stay independent.
    """
    if not gainers:
        return gainers

    keys = [f"analysis:{market}:{g.ticker}" for g in gainers]
    results = await asyncio.gather(*[cache.get(k) for k in keys], return_exceptions=True)

    enriched: list[StockGainer] = []
    for gainer, result in zip(gainers, results):
        if isinstance(result, dict):
            prediction = result.get("prediction") or {}
            pct = prediction.get("predicted_change_pct")
            conf = prediction.get("confidence")
            if pct is not None:
                gainer = gainer.model_copy(update={
                    "ai_prediction_pct": round(pct, 1),
                    "ai_prediction_confidence": round(conf, 2) if conf is not None else None,
                })
        enriched.append(gainer)
    return enriched


# ── Growth triggers context helper ────────────────────────────────────────────

def _format_gt_context(gt_data: dict) -> str | None:
    """
    Convert cached GrowthTriggersReport dict into a compact prompt section.
    Returns None if data is missing or malformed.
    Called just before the gainer_analyst AI call — zero extra latency
    because we only read from the cache that may already exist.
    """
    try:
        triggers = gt_data.get("triggers") or []
        if not triggers:
            return None
        lines = ["GROWTH TRIGGERS RESEARCH (from prior deep-dive analysis):"]
        for t in triggers[:4]:
            conviction = t.get("conviction", "MEDIUM")
            name = t.get("name", "")
            pl = t.get("p_and_l_impact", "")
            timeline = t.get("timeline", "")
            lines.append(f"  [{conviction}] {name}: {pl} · {timeline}")
        upside = gt_data.get("upside_scenario") or ""
        if upside:
            # Trim to keep the prompt tight
            lines.append(f"Upside scenario: {upside[:250]}")
        lines.append(
            "Use these catalysts to calibrate the 30-day prediction: "
            "HIGH conviction triggers warrant higher predicted_change_pct magnitude "
            "and confidence; OPTIONALITY triggers add upside but should not inflate base case."
        )
        return "\n".join(lines)
    except Exception:
        return None


# ── Cache key helpers ─────────────────────────────────────────────────────────
# No date in keys — expiry is controlled purely by TTL.
# This means the cache survives midnight and doesn't cold-start every morning.
# The Refresh button or TTL expiry are the only ways to get fresh data.

def _list_cache_key(market: Market, period: str = "1d") -> str:
    return f"gainers:{market}:{period}"


def _lkg_cache_key(market: Market, period: str = "1d") -> str:
    """Last-known-good: long TTL so data survives weekends and overnight Gemini failures."""
    return f"gainers:{market}:{period}:lkg"


def _is_market_hours(market: str) -> bool:
    """True while the relevant exchange is in regular trading hours (weekdays only)."""
    try:
        tz = ZoneInfo("America/New_York" if market == "us" else "Asia/Kolkata")
        now = datetime.now(tz)
        if now.weekday() >= 5:  # Saturday / Sunday
            return False
        minutes = now.hour * 60 + now.minute
        if market == "us":
            return 9 * 60 + 30 <= minutes < 16 * 60       # 9:30–16:00 ET
        return 9 * 60 + 15 <= minutes < 15 * 60 + 30      # 9:15–15:30 IST
    except Exception:
        return True  # assume open on any timezone error


_LKG_TTL: dict[str, int] = {"1d": 48 * 3600, "1w": 7 * 24 * 3600, "1m": 14 * 24 * 3600}


def _gainers_ttl(market: str, period: str, settings: Settings) -> int:
    """
    1d: 2 h during market hours, 24 h outside.
    1w: always 24 h (weekly snapshot changes slowly).
    1m: always 48 h (monthly snapshot).
    """
    if period == "1w":
        return 24 * 3600
    if period == "1m":
        return 48 * 3600
    return settings.gainers_list_ttl if _is_market_hours(market) else 24 * 3600


def _data_cache_key(ticker: str, market: Market) -> str:
    return f"data:{market}:{ticker}"


def _analysis_cache_key(ticker: str, market: Market) -> str:
    return f"analysis:{market}:{ticker}"


def _summary_cache_key(market: Market) -> str:
    return f"summary:{market}"


def _apply_quality_scores(gainers: list[StockGainer]) -> list[StockGainer]:
    result = []
    for g in gainers:
        score, label = compute_quality_score(g.price, g.volume, g.change_pct, g.ticker)
        result.append(g.model_copy(update={"quality_score": score, "quality_label": label}))
    return result


# ── List gainers ──────────────────────────────────────────────────────────────

@router.get("/{market}", response_model=GainersListResponse)
async def list_gainers(
    market: Annotated[Market, Path(description="'us' or 'india'")],
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    analyst: Annotated[MarketAnalystAgent, Depends(get_market_analyst)],
    news_fetcher: Annotated[NewsFetcher, Depends(get_news_fetcher)],
    gainer_analyst: Annotated[GainerAnalystAgent, Depends(get_gainer_analyst)],
    period: Annotated[Period, Query(description="Time window: 1d (today), 1w (1 week), 1m (1 month)")] = "1d",
    refresh: Annotated[bool, Query(description="Force bypass cache")] = False,
) -> GainersListResponse:
    """
    Return the top hybrid signals (movers + catalysts) for the given time window.
    Cache is TTL-based with a last-known-good fallback so users never see a blank page.
    """
    list_key = _list_cache_key(market, period)
    lkg_key = _lkg_cache_key(market, period)
    summary_key = _summary_cache_key(market)

    if not refresh:
        cached = await cache.get(list_key)
        if cached:
            log.info("gainers.list_cache_hit", market=market, period=period)
            gainers = [StockGainer(**g) for g in cached["gainers"]]
            gainers = await _enrich_with_predictions(gainers, market, cache)
            cached_summary = await cache.get(summary_key)
            summary = MarketSummary(**cached_summary) if cached_summary else None
            return GainersListResponse(
                market=market, period=period, date=today_str(),
                gainers=gainers, summary=summary, from_cache=True,
            )

    try:
        gainers = await market_data.get_gainers(market, period)
    except Exception as exc:
        log.error("gainers.list_fetch_error", market=market, period=period, error=str(exc))
        # Try main cache first, then last-known-good — never show a blank page on error
        for key in (list_key, lkg_key):
            stale = await cache.get(key)
            if stale:
                log.warning("gainers.serving_stale_on_error", market=market, period=period, key=key)
                gainers = [StockGainer(**g) for g in stale["gainers"]]
                gainers = await _enrich_with_predictions(gainers, market, cache)
                cached_summary = await cache.get(summary_key)
                summary = MarketSummary(**cached_summary) if cached_summary else None
                return GainersListResponse(
                    market=market, period=period, date=today_str(),
                    gainers=gainers, summary=summary, from_cache=True,
                )
        raise upstream_error("market data", str(exc))

    # Empty result (market closed, Gemini glitch, etc.): serve last-known-good
    # so users always see the most recent valid session instead of a blank page.
    if not gainers:
        log.warning("gainers.empty_result", market=market, period=period)
        lkg = await cache.get(lkg_key)
        if lkg:
            log.info("gainers.serving_lkg_on_empty", market=market, period=period)
            gainers_lkg = [StockGainer(**g) for g in lkg["gainers"]]
            gainers_lkg = await _enrich_with_predictions(gainers_lkg, market, cache)
            cached_summary = await cache.get(summary_key)
            summary = MarketSummary(**cached_summary) if cached_summary else None
            return GainersListResponse(
                market=market, period=period, date=today_str(),
                gainers=gainers_lkg, summary=summary, from_cache=True,
            )
        return GainersListResponse(
            market=market, period=period, date=today_str(),
            gainers=[], summary=None, from_cache=False,
        )

    ttl = _gainers_ttl(market, period, settings)

    # Market summary + cache write in parallel
    async def _get_summary() -> MarketSummary | None:
        try:
            s = await analyst.analyse(gainers, market)
            await cache.set(summary_key, s.model_dump(), ttl)
            return s
        except Exception as exc:
            log.warning("gainers.summary_failed", error=str(exc))
            return None

    summary, _, _ = await asyncio.gather(
        _get_summary(),
        cache.set(list_key, {"gainers": [g.model_dump() for g in gainers]}, ttl),
        cache.set(lkg_key, {"gainers": [g.model_dump() for g in gainers]}, _LKG_TTL[period]),
    )

    # Pre-warm AI analysis for top 5 only for the default 1d view (most likely to be clicked)
    if period == "1d":
        asyncio.create_task(
            _prewarm_top_analysis(gainers[:5], market, cache, market_data, news_fetcher, gainer_analyst, settings)
        )

    gainers = await _enrich_with_predictions(gainers, market, cache)
    return GainersListResponse(
        market=market, period=period, date=today_str(),
        gainers=gainers, summary=summary, from_cache=False,
    )


async def _prewarm_top_analysis(
    gainers: list[StockGainer],
    market: Market,
    cache: CacheBackend,
    market_data: MarketDataService,
    news_fetcher: NewsFetcher,
    analyst: GainerAnalystAgent,
    settings: Settings,
) -> None:
    """
    Background task: pre-generate AI analysis for the top gainers so the first
    user click on any of them is served from cache (instant) instead of cold
    (15-20 s Gemini call).  Runs up to 3 concurrently via semaphore to balance
    speed against Vertex AI rate limits.
    """
    sem = asyncio.Semaphore(settings.prewarm_concurrency)

    async def _warm_one(gainer: StockGainer) -> None:
        key = _analysis_cache_key(gainer.ticker, market)
        async with sem:
            try:
                if await cache.get(key):
                    return  # already warm
                log.info("gainers.prewarm_start", ticker=gainer.ticker, market=market)
                fundamentals, news = await asyncio.gather(
                    market_data.get_fundamentals(gainer.ticker, market),
                    news_fetcher.get_news(gainer.ticker, gainer.name, market=market),
                    return_exceptions=True,
                )
                analysis, prediction = await analyst.analyse_full(
                    ticker=gainer.ticker,
                    change_pct=gainer.change_pct,
                    company_name=gainer.name,
                    sector=gainer.sector,
                    news=news if not isinstance(news, Exception) else [],
                    fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
                    gainers_context=None,
                )
                response = StockAnalysisResponse(
                    ticker=gainer.ticker,
                    market=market,
                    analysis=analysis,
                    prediction=prediction,
                    from_cache=False,
                    analysed_at=datetime.utcnow(),
                )
                await cache.set(key, response.model_dump(), settings.analysis_ttl)
                log.info("gainers.prewarm_done", ticker=gainer.ticker, market=market)
            except Exception as exc:
                log.warning("gainers.prewarm_failed", ticker=gainer.ticker, error=str(exc))

    await asyncio.gather(*[_warm_one(g) for g in gainers])


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
            return GainerDetail(**{**cached, "from_cache": True})

    # _resolve_gainer returns the raw yfinance info dict alongside the StockGainer.
    # When the gainer came from the cached gainers list the dict is empty ({}),
    # meaning we still need a separate fundamentals call.  When it came from a
    # live yfinance lookup the dict is already populated and we can extract
    # fundamentals directly — saving a full second round-trip to Yahoo Finance.
    gainer, yf_info = await _resolve_gainer(ticker, market, market_data, cache)
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
        news_fetcher.get_news(ticker, gainer.name, market=market),
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

    # If news is empty the API source was likely rate-limited or unreachable —
    # cache briefly so the next request retries quickly rather than serving
    # stale empty-news for the full 2-hour TTL.
    detail_ttl = settings.gainers_list_ttl if news else 120
    await cache.set(key, detail.model_dump(), detail_ttl)
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
    quarterly_fetcher: Annotated[QuarterlyFetcher, Depends(get_quarterly_fetcher)],
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
            return StockAnalysisResponse(**{**cached, "from_cache": True})

    # Resolve gainer + gainers list in parallel (list used for comparison context)
    (gainer, _yf_info), gainers_list = await asyncio.gather(
        _resolve_gainer(ticker, market, market_data, cache),
        _safe_get_gainers(market, cache),
    )

    if gainer is None:
        raise ticker_not_found(ticker)

    # Use the resolved ticker (e.g. "NVDA") not the raw query (e.g. "NVIDIA")
    # for all downstream calls so Gemini gets a real ticker symbol.
    resolved_ticker = gainer.ticker

    # Determine whether this ticker is in today's gainer list
    in_gainers = any(g.ticker == resolved_ticker for g in gainers_list)
    gainers_context = gainers_list[:3] if not in_gainers and gainers_list else None

    # Fetch fundamentals + news + price history in parallel.
    # Price history → technical indicators → injected into Gemini prompt.
    import yfinance as yf
    from services.technicals import compute_technicals, format_for_prompt as fmt_technicals

    async def _get_analysis_fundamentals():
        if _yf_info:
            return fundamentals_from_info(_yf_info)
        try:
            return await market_data.get_fundamentals(resolved_ticker, market)
        except Exception as exc:
            log.warning("gainers.analysis_fundamentals_failed", ticker=resolved_ticker, error=str(exc))
            return None

    async def _get_quarterly_data() -> "QuarterlySnapshot | None":
        """Fetch quarterly results from screener.in (India) or yfinance (US).
        Cached 24 h — results only change once a quarter.
        Hard-capped at 6 s total so it never blocks the Gemini call."""
        from models.schemas import QuarterlySnapshot
        from services.quarterly_fetcher import _compute_quarterly_insight
        q_key = f"quarterly:{market}:{resolved_ticker}"
        cached_q = await cache.get(q_key)
        if cached_q:
            log.info("gainers.quarterly_cache_hit", ticker=resolved_ticker)
            snap = QuarterlySnapshot(**cached_q)
            # Always recompute the insight from the cached trend data — pure Python,
            # no I/O, so no overhead.  This ensures any improvement to
            # _compute_quarterly_insight is picked up without waiting 24 h for
            # the quarterly cache to expire or requiring a manual re-analyse.
            if snap.quarters:
                fresh_insight = _compute_quarterly_insight(
                    snap.revenue_trend, snap.margin_trend,
                    snap.earnings_trend, snap.quarters,
                )
                if fresh_insight != snap.quarterly_insight:
                    snap = snap.model_copy(update={"quarterly_insight": fresh_insight})
                    await cache.set(q_key, snap.model_dump(), 24 * 3600)
            return snap

        try:
            snap = await asyncio.wait_for(
                quarterly_fetcher.fetch(resolved_ticker, market),
                timeout=6.0,
            )
        except asyncio.TimeoutError:
            log.warning("gainers.quarterly_timeout", ticker=resolved_ticker)
            return None

        if snap is None:
            return None

        await cache.set(q_key, snap.model_dump(), 24 * 3600)
        return snap

    async def _get_price_history() -> list[dict]:
        # Try NSE first, fall back to BSE for India (some stocks only on BSE)
        suffixes = (".NS", ".BO") if market == "india" else ("",)
        for suffix in suffixes:
            yf_sym = f"{resolved_ticker}{suffix}" if market == "india" else resolved_ticker
            try:
                hist = await asyncio.wait_for(
                    asyncio.to_thread(lambda s=yf_sym: yf.Ticker(s).history(period="3mo", interval="1d")),
                    timeout=10.0,
                )
                if not hist.empty:
                    candles = []
                    for ts, row in hist.iterrows():
                        candles.append({
                            "time": int(ts.timestamp()),
                            "open": float(row["Open"]), "high": float(row["High"]),
                            "low": float(row["Low"]),  "close": float(row["Close"]),
                            "volume": int(row["Volume"]),
                        })
                    return candles
            except Exception as exc:
                log.warning("gainers.price_history_failed", ticker=resolved_ticker, error=str(exc))
        return []

    fundamentals_result, news, candles, quarterly_text_result = await asyncio.gather(
        _get_analysis_fundamentals(),
        news_fetcher.get_news(resolved_ticker, gainer.name, market=market),
        # Hard cap: India stocks try .NS then .BO (10 s each = 20 s worst case).
        # Cap at 8 s total so Gemini always has headroom before the server timeout.
        asyncio.wait_for(_get_price_history(), timeout=8.0),
        _get_quarterly_data(),
        return_exceptions=True,
    )

    fundamentals = fundamentals_result if not isinstance(fundamentals_result, Exception) else None
    if isinstance(news, Exception):
        log.warning("gainers.analysis_news_failed", ticker=resolved_ticker, error=str(news))
        news = []
    if isinstance(candles, Exception):
        candles = []
    quarterly_snap = quarterly_text_result if not isinstance(quarterly_text_result, Exception) else None
    quarterly_text: str | None = fmt_quarterly(quarterly_snap) if quarterly_snap else None
    if quarterly_text:
        log.info("gainers.quarterly_injected", ticker=resolved_ticker, chars=len(quarterly_text))

    # Compute technical indicators from price history
    technicals = None
    technicals_text: str | None = None
    if candles:
        try:
            currency = "₹" if market == "india" else "$"
            technicals = compute_technicals(candles, gainer.price)
            technicals_text = fmt_technicals(technicals, gainer.price, currency)
            log.info(
                "gainers.technicals_computed",
                ticker=resolved_ticker,
                rsi=technicals.rsi_14,
                macd_direction=technicals.macd_direction,
                candles=len(candles),
            )
        except Exception as exc:
            log.warning("gainers.technicals_failed", ticker=resolved_ticker, error=str(exc))

    # If Growth Triggers results are already cached for this ticker, inject them
    # as context so the 30-day prediction magnitude/confidence reflects real catalysts.
    # Zero latency cost — we only read from cache; GT is never triggered here.
    gt_raw = await cache.get(f"growth-triggers:{market}:{resolved_ticker}")
    gt_context: str | None = _format_gt_context(gt_raw) if gt_raw else None
    if gt_context:
        log.info("gainers.gt_context_injected", ticker=resolved_ticker)

    # Single combined Gemini call — analysis + 30-day prediction (now includes technical signals)
    analysis = None
    prediction = None
    is_mock_fallback = False
    try:
        analysis, prediction = await analyst.analyse_full(
            ticker=resolved_ticker,
            change_pct=gainer.change_pct,
            company_name=gainer.name,
            sector=gainer.sector,
            news=news if not isinstance(news, Exception) else [],
            fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
            gainers_context=gainers_context,
            technicals_text=technicals_text,
            quarterly_text=quarterly_text,
            growth_triggers_context=gt_context,
        )
    except Exception as exc:
        log.error("gainers.ai_failed", ticker=resolved_ticker, error=str(exc))
        try:
            mock_agent = GainerAnalystAgent(settings.model_copy(update={"mock_ai": True}))
            analysis, prediction = await mock_agent.analyse_full(
                ticker=resolved_ticker,
                change_pct=gainer.change_pct,
                company_name=gainer.name,
                sector=gainer.sector,
                news=news if not isinstance(news, Exception) else [],
                fundamentals=fundamentals if not isinstance(fundamentals, Exception) else None,
                gainers_context=gainers_context,
                technicals_text=technicals_text,
                quarterly_text=quarterly_text,
                growth_triggers_context=gt_context,
            )
            is_mock_fallback = True
            log.info("gainers.ai_fallback_mock_used", ticker=resolved_ticker)
        except Exception as fallback_exc:
            log.error("gainers.ai_fallback_failed", ticker=resolved_ticker, error=str(fallback_exc))

    response = StockAnalysisResponse(
        ticker=resolved_ticker,
        market=market,
        analysis=analysis,
        prediction=prediction,
        technicals=technicals,
        quarterly=quarterly_snap,
        from_cache=False,
        analysed_at=datetime.utcnow(),
    )

    # Only cache real Gemini responses — mock fallbacks are retried fresh on next request.
    if not is_mock_fallback:
        await cache.set(key, response.model_dump(), settings.analysis_ttl)
    return response


# ── Price history (candlestick data) ─────────────────────────────────────────

@router.get("/{market}/{ticker}/history")
async def get_price_history(
    market: Annotated[Market, Path()],
    ticker: Annotated[str, Path()],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    period: Annotated[str, Query(description="yfinance period: 1mo, 3mo, 6mo, 1y")] = "3mo",
) -> dict:
    """
    OHLCV candlestick data for a ticker. Used by the price chart in AnalysisPanel.
    Cached 30 minutes — stale enough to survive re-clicks, fresh enough for intraday charts.
    """
    import asyncio
    import yfinance as yf

    ticker = ticker.upper()
    key = f"history:{market}:{ticker}:{period}"

    cached = await cache.get(key)
    if cached:
        return cached

    # Try NSE first, fall back to BSE for India (some stocks only on BSE)
    hist = None
    for suffix in (".NS", ".BO") if market == "india" else ("",):
        yf_sym = f"{ticker}{suffix}" if market == "india" else ticker
        try:
            h = await asyncio.wait_for(
                asyncio.to_thread(lambda s=yf_sym: yf.Ticker(s).history(period=period, interval="1d")),
                timeout=10.0,
            )
            if not h.empty:
                hist = h
                break
        except Exception as exc:
            log.warning("gainers.history_failed", ticker=ticker, error=str(exc))

    if hist is None or hist.empty:
        return {"ticker": ticker, "candles": []}

    candles = []
    for ts, row in hist.iterrows():
        try:
            candles.append({
                "time": int(ts.timestamp()),
                "open":  round(float(row["Open"]),  4),
                "high":  round(float(row["High"]),  4),
                "low":   round(float(row["Low"]),   4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        except Exception:
            continue

    result = {"ticker": ticker, "period": period, "candles": candles}
    await cache.set(key, result, 30 * 60)  # 30 min TTL
    return result


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
    ticker: str, market: Market, market_data: MarketDataService,
    cache: CacheBackend | None = None,
) -> tuple[StockGainer | None, dict]:
    """
    Resolve a ticker string to a StockGainer record.

    Returns (gainer, raw_yf_info) where:
      - raw_yf_info is non-empty when the gainer was resolved via yfinance
        (callers can extract FundamentalsData directly without a second call).
      - raw_yf_info is {} when the gainer came from the cached gainers list
        (callers should fetch fundamentals via market_data.get_fundamentals).

    Strategy:
      1. Check cached gainers lists (instant, reads from cache — no Gemini).
      2. Direct yfinance lookup.
      3. If yfinance returns no price, resolve company name → ticker via
         Gemini / Yahoo Finance search, then retry yfinance.
    """
    import yfinance as yf
    from services.market_data import _safe_float, _safe_int

    def _best_price(d: dict) -> float:
        """yfinance field priority: regularMarketPrice > currentPrice > previousClose.
        regularMarketPrice is None outside market hours on some tickers."""
        return (
            d.get("regularMarketPrice")
            or d.get("currentPrice")
            or d.get("previousClose")
            or 0.0
        )

    # ── Step 1a: ticker-resolution cache (instant) ────────────────────────────
    # Both the detail and analyse endpoints fire in parallel for a new search.
    # Without this cache each would independently call Gemini (~15 s) + yfinance
    # (~8 s) to resolve "NVIDIA" → "NVDA".  After the first resolution the
    # mapping is cached for 24 h, making every subsequent lookup instant.
    _res_cache_key = f"ticker_res:{market}:{ticker.lower()}"
    if cache is not None:
        res_cached = await cache.get(_res_cache_key)
        if res_cached:
            ticker = res_cached["resolved"]
            log.info("gainers.ticker_res_cache_hit", resolved=ticker, market=market)

    # ── Step 1b: cached gainers lists (instant — reads from cache, no Gemini) ─
    if cache is not None:
        for period in ("1d", "1w", "1m"):
            cached_list = await cache.get(_list_cache_key(market, period))
            if cached_list:
                match = next(
                    (StockGainer(**g) for g in cached_list["gainers"] if g["ticker"] == ticker),
                    None,
                )
                if match:
                    return match, {}

    # ── Helpers ───────────────────────────────────────────────────────────────
    async def _yf_lookup(sym: str) -> dict:
        """yfinance lookup with a hard 8-second timeout.
        For India, tries NSE (.NS) first then BSE (.BO) as fallback —
        some stocks (e.g. VOEPL) only trade on BSE."""
        if market == "india":
            for suffix in (".NS", ".BO"):
                yf_sym = f"{sym}{suffix}"
                try:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(lambda s=yf_sym: yf.Ticker(s).info),
                        timeout=8.0,
                    )
                    if _best_price(info):
                        return info
                except asyncio.TimeoutError:
                    log.warning("gainers.yf_lookup_timeout", ticker=sym)
                except Exception:
                    pass
            return {}
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(lambda: yf.Ticker(sym).info),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            log.warning("gainers.yf_lookup_timeout", ticker=sym)
            return {}
        except Exception:
            return {}

    def _looks_like_company_name(s: str) -> bool:
        """Heuristic: skip direct yfinance and go straight to name/ticker resolution.
        US tickers are ≤5 chars (NVDA, AAPL, MSFT).
        Indian NSE/BSE tickers can be up to 10 chars (TRANSRAIL=9, TATASTEEL=9,
        HDFCBANK=8) — so we only treat it as a 'company name' if it exceeds that."""
        threshold = 10 if market == "india" else 5
        return len(s) > threshold and s.isalpha()

    info: dict = {}

    # ── Step 2: direct yfinance (only for plausible tickers, ≤5 chars) ───────
    if not _looks_like_company_name(ticker):
        info = await _yf_lookup(ticker)

    # ── Step 3: name/ticker resolution ───────────────────────────────────────
    # Triggered when: (a) input looks like a company name, or (b) yfinance
    # returned no price for what looked like a ticker (e.g. outdated symbol).
    original_query = ticker
    if not info or not _best_price(info):
        resolved = await resolve_ticker_by_name(ticker, market)
        if resolved:
            resolved_upper = resolved.upper()
            if resolved_upper != ticker:
                # Gemini mapped a company name to a different ticker symbol
                log.info("gainers.ticker_resolved", query=ticker, resolved=resolved_upper, market=market)
                ticker = resolved_upper
            # Always do yfinance after Gemini resolution — even when resolved
            # equals input (e.g. TRANSRAIL → "TRANSRAIL" on NSE/BSE).
            info = await _yf_lookup(ticker)
            # Cache the resolution so parallel/future requests skip Gemini+yfinance
            if cache is not None and _best_price(info):
                await cache.set(
                    f"ticker_res:{market}:{original_query.lower()}",
                    {"resolved": ticker},
                    24 * 3600,
                )

    price = _best_price(info) if info else 0.0
    if not price:
        return None, {}

    change_pct = info.get("regularMarketChangePercent") or 0.0
    # Pass the real value through — can be negative for searched non-gainers.
    # The validator no longer enforces positive-only; the UI handles sign/colour.

    gainer = StockGainer(
        ticker=ticker,
        name=info.get("shortName") or info.get("longName") or ticker,
        market=market,
        price=float(price),
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
    market: Market, cache: CacheBackend,
) -> list[StockGainer]:
    """Return today's cached gainers list for AI comparison context.
    Reads from cache only — never triggers a live Gemini call."""
    cached = await cache.get(_list_cache_key(market, "1d"))
    if cached:
        try:
            return [StockGainer(**g) for g in cached["gainers"]]
        except Exception:
            pass
    return []
