"""
QualityDipScreener — QARP candidates for the allocation plan stock picker.

Instead of today's gainers (momentum-biased), this screener finds stocks from
a curated universe that are:
  1. Fundamentally strong  (fundamental_score >= 5.5)
  2. Available at a dip   (>= 10% below their 52-week high)
  3. Not structurally broken (no "negative 5yr return" warning)

Composite score = fundamental_score × 0.6 + dip_quality × 0.4
Cache key: quality_dips:{market}:{risk_profile}  TTL: 24 h
"""
from __future__ import annotations

import asyncio
from typing import Any

from core.logging import get_logger
from services.fundamental_scoring import _SCORE_CACHE_VERSION, get_fundamental_score

log = get_logger(__name__)

_DIP_TTL = 24 * 3600

# ── Curated quality universe ───────────────────────────────────────────────────
# Nifty 200 representative — liquid, well-governed, institutional coverage

_INDIA_UNIVERSE = [
    "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTIM.NS",
    "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS",
    "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "BAJFINANCE.NS", "BAJAJFINSV.NS", "MUTHOOTFIN.NS",
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS", "MARICO.NS",
    "TITAN.NS", "ASIANPAINT.NS", "PIDILITIND.NS",
    "RELIANCE.NS", "BHARTIARTL.NS",
    "LT.NS", "SIEMENS.NS", "ABB.NS", "CUMMINSIND.NS", "THERMAX.NS",
    "HAL.NS", "BEL.NS", "GRSE.NS",
    "NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS", "ADANIGREEN.NS",
    "MARUTI.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS", "TVSMOTOR.NS",
    "TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS",
    "DMART.NS", "TRENT.NS",
    "SRF.NS", "PIIND.NS",
    "WABAG.NS",
]

_US_UNIVERSE = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO",
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "AMGN",
    "JPM", "V", "MA", "BAC", "GS",
    "HD", "WMT", "PG", "KO", "PEP", "COST",
    "CRWD", "PANW", "NOW", "CRM", "SNOW",
    "RTX", "LMT", "NOC", "GD",
    "NEE", "CEG",
    "SPGI", "MCO", "ICE",
    "TMO", "DHR", "ISRG",
    "CAT", "HON", "DE",
]


def _dip_quality(pct_from_high: float) -> float:
    """0–10 score for how attractive the dip is. Deeper dip = higher score."""
    if pct_from_high <= -30:
        return 10.0
    if pct_from_high <= -20:
        return 8.0
    if pct_from_high <= -15:
        return 6.5
    if pct_from_high <= -10:
        return 5.0
    if pct_from_high <= -5:
        return 2.5
    return 0.0  # at or near 52-week high — no dip bonus


async def _score_ticker(
    ticker: str,
    market: str,
    risk_profile: str,
    cache: Any,
    refresh: bool = False,
) -> dict | None:
    """Fetch fundamental score + dip depth. Returns None if data unavailable."""
    try:
        result = await get_fundamental_score(ticker, market, risk_profile, cache, refresh=refresh)
        if result is None:
            return None

        fscore   = result.get("fundamental_score", 0)
        warnings = result.get("warnings", [])

        # Structural disqualifiers
        if any("negative 5-year return" in w.lower() or "negative roe" in w.lower() for w in warnings):
            return None
        if fscore < 5.5:
            return None

        # Fetch 52w high from yfinance info (already fetched inside fundamental_scoring; repeat is lightweight)
        import yfinance as yf

        def _get_price_info() -> dict | None:
            info = yf.Ticker(ticker).info or {}
            price   = info.get("currentPrice") or info.get("regularMarketPrice")
            hi52    = info.get("fiftyTwoWeekHigh")
            name    = info.get("shortName") or info.get("longName") or ticker
            sector  = info.get("sector", "Unknown")
            if not price or not hi52 or hi52 <= 0:
                return None
            pct_from_high = round((price - hi52) / hi52 * 100, 1)
            return {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "price": round(float(price), 2),
                "pct_from_52w_high": pct_from_high,
            }

        price_info = await asyncio.wait_for(asyncio.to_thread(_get_price_info), timeout=10.0)
        if price_info is None:
            return None

        pct_from_high = price_info["pct_from_52w_high"]

        # Must be at least 8% below 52w high to qualify as a dip
        if pct_from_high > -8.0:
            return None

        dip_q     = _dip_quality(pct_from_high)
        composite = round(fscore * 0.6 + dip_q * 0.4, 2)

        return {
            "ticker": ticker,
            "name": price_info["name"],
            "sector": price_info["sector"],
            "price": price_info["price"],
            "pct_from_52w_high": pct_from_high,
            "fundamental_score": fscore,
            "grade": result.get("grade", "?"),
            "dip_quality": dip_q,
            "composite_score": composite,
            "key_metrics": result.get("key_metrics", {}),
            "warnings": warnings,
            "signal_tier": "catalyst",   # keep compat with advisor route
            "quality_score": round(fscore * 10, 1),  # compat field
            "change_pct": pct_from_high,  # re-use field: negative = dipped
        }

    except Exception as exc:
        log.warning("quality_dip.score_failed", ticker=ticker, error=str(exc))
        return None


async def get_quality_dip_candidates(
    market: str,
    risk_profile: str,
    cache: Any,
    refresh: bool = False,
    max_results: int = 15,
) -> list[dict]:
    """
    Return top QARP candidates for the given market and investor risk profile.
    Cached 24 h per market+profile combination.
    """
    # Versioned so a scoring-logic change auto-invalidates stale candidate lists on deploy.
    cache_key = f"quality_dips:{_SCORE_CACHE_VERSION}:{market}:{risk_profile}"

    if not refresh:
        cached = await cache.get(cache_key)
        if cached:
            log.info("quality_dip.cache_hit", market=market, risk_profile=risk_profile)
            return cached

    universe = _INDIA_UNIVERSE if market == "india" else _US_UNIVERSE
    sem = asyncio.Semaphore(5)

    async def _guarded(ticker: str) -> dict | None:
        async with sem:
            return await _score_ticker(ticker, market, risk_profile, cache, refresh=refresh)

    log.info("quality_dip.screen_start", market=market, universe=len(universe))
    raw = await asyncio.gather(*[_guarded(t) for t in universe], return_exceptions=True)

    candidates = [
        r for r in raw
        if isinstance(r, dict) and r is not None
    ]

    # Sort by composite score (fundamental quality × 0.6 + dip attractiveness × 0.4)
    candidates.sort(key=lambda c: c["composite_score"], reverse=True)
    top = candidates[:max_results]

    await cache.set(cache_key, top, _DIP_TTL)

    log.info(
        "quality_dip.screen_done",
        market=market,
        screened=len(universe),
        qualified=len(candidates),
        returned=len(top),
    )
    return top
