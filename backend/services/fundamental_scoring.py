"""
Fundamental quality scoring for individual stocks.

Replaces the momentum-only compute_quality_score (price/volume/change_pct)
with a real fundamental assessment:

  • 5-year CAGR vs market benchmark  (how has the stock actually performed?)
  • Return on Equity                  (is the business profitable?)
  • Revenue growth (YoY)             (is the business growing?)
  • Debt/Equity ratio                (is the balance sheet safe?)
  • Institutional ownership          (are smart-money buyers present?)

Weights shift by risk profile so the same stock scores differently for an
aggressive vs conservative investor — high-debt, high-growth works for
aggressive; safe, dividend-paying compounders win for conservative.

Cached 24 h per ticker — fundamentals barely change day-to-day.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from core.logging import get_logger
from services.cache import CacheBackend

log = get_logger(__name__)

# Approximate 5-year annualised benchmark returns (used to compute alpha)
_BENCHMARK_CAGR: dict[str, float] = {
    "india": 0.13,   # Nifty 50 ~13% CAGR
    "us":    0.14,   # S&P 500 ~14% CAGR
}

_CACHE_TTL = 24 * 3600   # 24 h — fundamentals are slow-moving

# Bump this whenever the SCORING LOGIC changes (new component, reweighting,
# threshold change). It is part of the score cache key, so a deploy with a new
# version silently invalidates every stale cached score — no manual refresh or
# Redis flush needed. v2 = added valuation (P/B) component.
_SCORE_CACHE_VERSION = "v2"


# ── Weights by risk profile ──────────────────────────────────────────────────

_WEIGHTS: dict[str, dict[str, float]] = {
    "aggressive": {
        "historical_performance": 0.30,
        "revenue_growth":         0.22,
        "profitability_roe":      0.18,
        "debt_safety":            0.10,
        "institutional_interest": 0.10,
        "valuation":              0.10,   # growth investors tolerate premium; still can't ignore it
    },
    "moderate": {
        "historical_performance": 0.20,
        "revenue_growth":         0.18,
        "profitability_roe":      0.22,
        "debt_safety":            0.18,
        "institutional_interest": 0.10,
        "valuation":              0.12,
    },
    "conservative": {
        "historical_performance": 0.15,
        "revenue_growth":         0.10,
        "profitability_roe":      0.20,
        "debt_safety":            0.30,
        "institutional_interest": 0.10,
        "valuation":              0.15,   # conservative investors must not overpay
    },
}


# ── Component scorers (each returns 0–10) ───────────────────────────────────

def _score_historical(cagr: Optional[float], benchmark: float) -> tuple[float, str]:
    if cagr is None:
        return 5.0, "no data"
    alpha = cagr - benchmark
    if alpha >= 0.10:
        return 10.0, f"{cagr*100:.1f}% CAGR (+{alpha*100:.1f}% vs benchmark)"
    if alpha >= 0.05:
        return 8.0,  f"{cagr*100:.1f}% CAGR (+{alpha*100:.1f}% vs benchmark)"
    if alpha >= 0.0:
        return 6.0,  f"{cagr*100:.1f}% CAGR (in line with benchmark)"
    if alpha >= -0.05:
        return 3.0,  f"{cagr*100:.1f}% CAGR ({alpha*100:.1f}% vs benchmark)"
    if alpha >= -0.10:
        return 1.5,  f"{cagr*100:.1f}% CAGR ({alpha*100:.1f}% vs benchmark)"
    return 0.0, f"{cagr*100:.1f}% CAGR (badly trails benchmark)"


def _score_roe(roe: Optional[float]) -> tuple[float, str]:
    if roe is None:
        return 5.0, "no data"
    pct = roe * 100
    if roe >= 0.25:
        return 10.0, f"ROE {pct:.1f}% (excellent)"
    if roe >= 0.20:
        return 8.0,  f"ROE {pct:.1f}% (strong)"
    if roe >= 0.15:
        return 6.0,  f"ROE {pct:.1f}% (healthy)"
    if roe >= 0.10:
        return 4.0,  f"ROE {pct:.1f}% (adequate)"
    if roe >= 0.0:
        return 2.0,  f"ROE {pct:.1f}% (weak)"
    return 0.0, f"ROE {pct:.1f}% (negative — destroying capital)"


def _score_revenue_growth(growth: Optional[float]) -> tuple[float, str]:
    if growth is None:
        return 5.0, "no data"
    pct = growth * 100
    if growth >= 0.30:
        return 10.0, f"Revenue growth {pct:.1f}% YoY (exceptional)"
    if growth >= 0.20:
        return 8.0,  f"Revenue growth {pct:.1f}% YoY (strong)"
    if growth >= 0.10:
        return 6.0,  f"Revenue growth {pct:.1f}% YoY (solid)"
    if growth >= 0.0:
        return 4.0,  f"Revenue growth {pct:.1f}% YoY (flat)"
    return 0.0, f"Revenue growth {pct:.1f}% YoY (contracting)"


def _score_debt(de_raw: Optional[float]) -> tuple[float, str]:
    """yfinance returns debtToEquity in percentage form (50.0 = 0.5x)."""
    if de_raw is None:
        return 5.0, "no data"
    de = de_raw / 100.0   # normalise to ratio
    if de <= 0.1:
        return 10.0, f"D/E {de:.2f}x (virtually debt-free)"
    if de <= 0.3:
        return 8.0,  f"D/E {de:.2f}x (conservative)"
    if de <= 0.5:
        return 6.0,  f"D/E {de:.2f}x (manageable)"
    if de <= 1.0:
        return 4.0,  f"D/E {de:.2f}x (elevated)"
    if de <= 2.0:
        return 2.0,  f"D/E {de:.2f}x (high leverage)"
    return 0.0, f"D/E {de:.2f}x (dangerous leverage)"


def _score_valuation(pb: Optional[float], pe: Optional[float]) -> tuple[float, str]:
    """
    Price-to-book as the primary valuation anchor, with P/E as fallback.
    A deep dip that still leaves you at P/B 10x is not margin of safety.

    Only POSITIVE P/B is a valid value signal. Negative P/B means negative book
    equity (heavy buybacks like MCD/ABBV, or accumulated losses) — it tells us
    nothing about cheapness, so we fall back to P/E. Likewise only positive P/E
    is meaningful; a negative P/E (loss-making) is left to ROE/margins to penalise.
    """
    if pb is not None and pb > 0:
        if pb <= 1.0:
            return 10.0, f"P/B {pb:.1f}x (at or below book — strong margin of safety)"
        if pb <= 2.5:
            return 8.0,  f"P/B {pb:.1f}x (reasonable premium for quality)"
        if pb <= 4.0:
            return 6.0,  f"P/B {pb:.1f}x (moderate premium)"
        if pb <= 6.0:
            return 4.0,  f"P/B {pb:.1f}x (expensive — dip does not create deep value)"
        if pb <= 10.0:
            return 2.0,  f"P/B {pb:.1f}x (very expensive — price dip still leaves high premium)"
        return 0.5,      f"P/B {pb:.1f}x (extreme premium — even after dip, far from value)"

    # Fallback: P/E, only meaningful when positive (profitable)
    if pe is not None and pe > 0:
        if pe <= 15:
            return 8.0, f"P/E {pe:.0f}x (reasonable)"
        if pe <= 25:
            return 6.0, f"P/E {pe:.0f}x (moderate premium)"
        if pe <= 40:
            return 4.0, f"P/E {pe:.0f}x (expensive)"
        return 1.5, f"P/E {pe:.0f}x (very expensive — limited margin of safety)"

    return 5.0, "valuation data unavailable (negative book value / no earnings)"


def _score_institutional(held_pct: Optional[float]) -> tuple[float, str]:
    """heldPercentInstitutions is a decimal (0.35 = 35%)."""
    if held_pct is None:
        return 3.0, "no data"
    pct = held_pct * 100
    if held_pct >= 0.40:
        return 10.0, f"Institutional holdings {pct:.1f}% (high conviction)"
    if held_pct >= 0.30:
        return 8.0,  f"Institutional holdings {pct:.1f}% (strong interest)"
    if held_pct >= 0.20:
        return 6.0,  f"Institutional holdings {pct:.1f}% (moderate)"
    if held_pct >= 0.10:
        return 4.0,  f"Institutional holdings {pct:.1f}% (low)"
    if held_pct >= 0.05:
        return 2.0,  f"Institutional holdings {pct:.1f}% (minimal)"
    return 1.0, f"Institutional holdings {pct:.1f}% (almost none)"


# ── Core computation ─────────────────────────────────────────────────────────

def compute_fundamental_score(
    info: dict[str, Any],
    five_yr_cagr: Optional[float],
    market: str,
    risk_profile: str,
) -> dict[str, Any]:
    """
    Returns:
        fundamental_score  float 0–10
        grade              "A" / "B" / "C" / "D" / "F"
        breakdown          component label → (score, description)
        warnings           list of red-flag strings
        key_metrics        dict of raw values for the AI prompt
    """
    benchmark = _BENCHMARK_CAGR.get(market, 0.13)
    weights = _WEIGHTS.get(risk_profile, _WEIGHTS["moderate"])

    def _safe(key: str) -> Optional[float]:
        v = info.get(key)
        if v is None or v != v:   # None or NaN
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # Raw values
    roe        = _safe("returnOnEquity")
    rev_growth = _safe("revenueGrowth")
    de_raw     = _safe("debtToEquity")
    inst_held  = _safe("heldPercentInstitutions")
    pe         = _safe("trailingPE")
    pb         = _safe("priceToBook")
    div_yield  = _safe("dividendYield")
    eps_growth = _safe("earningsGrowth")
    profit_margin = _safe("profitMargins")

    # Component scores
    hist_score, hist_desc = _score_historical(five_yr_cagr, benchmark)
    roe_score,  roe_desc  = _score_roe(roe)
    rev_score,  rev_desc  = _score_revenue_growth(rev_growth)
    debt_score, debt_desc = _score_debt(de_raw)
    inst_score, inst_desc = _score_institutional(inst_held)
    val_score,  val_desc  = _score_valuation(pb, pe)

    breakdown = {
        "historical_performance": (hist_score, hist_desc),
        "profitability_roe":      (roe_score,  roe_desc),
        "revenue_growth":         (rev_score,  rev_desc),
        "debt_safety":            (debt_score, debt_desc),
        "institutional_interest": (inst_score, inst_desc),
        "valuation":              (val_score,  val_desc),
    }

    # Weighted total (0–10)
    total = sum(
        breakdown[k][0] * weights[k]
        for k in weights
    )

    # Risk-profile bonuses / penalties
    if risk_profile == "conservative":
        if pe and pe > 30:
            total -= 0.5   # softened — the valuation component now carries most of this
        if div_yield and div_yield > 0.02:
            total += 0.5   # bonus for income component
    elif risk_profile == "aggressive":
        if eps_growth and eps_growth > 0.20:
            total += 0.5   # bonus for strong earnings momentum

    total = max(0.0, min(10.0, round(total, 1)))

    # Grade
    if total >= 8.0:
        grade = "A"
    elif total >= 6.5:
        grade = "B"
    elif total >= 5.0:
        grade = "C"
    elif total >= 3.0:
        grade = "D"
    else:
        grade = "F"

    # Warnings (surfaced to AI and user)
    warnings: list[str] = []
    if five_yr_cagr is not None and five_yr_cagr < 0:
        warnings.append(f"Negative 5-year return ({five_yr_cagr*100:.1f}%) — stock has destroyed value")
    if roe is not None and roe < 0:
        warnings.append(f"Negative ROE — business not generating profit on equity")
    if rev_growth is not None and rev_growth < 0:
        warnings.append(f"Revenue contracting ({rev_growth*100:.1f}% YoY)")
    if de_raw is not None and de_raw / 100 > 1.5:
        warnings.append(f"High leverage (D/E {de_raw/100:.1f}x) — interest cost risk")
    # Valuation warnings — apply to all profiles, thresholds shift by profile.
    # Only positive P/B is meaningful (negative = negative book equity, not "cheap").
    pb_warn_threshold = 6.0 if risk_profile == "conservative" else 8.0
    if pb is not None and pb > pb_warn_threshold:
        warnings.append(
            f"P/B {pb:.1f}x — expensive even after price dip; "
            f"paying {pb:.0f}x book for every rupee of assets limits margin of safety"
        )
    pe_warn_threshold = 30 if risk_profile == "conservative" else 45
    if pe is not None and pe > pe_warn_threshold:
        warnings.append(f"P/E {pe:.0f}x — growth priced in; limited room for error")

    key_metrics: dict[str, Any] = {}
    if five_yr_cagr is not None:
        key_metrics["5yr_cagr"] = f"{five_yr_cagr*100:.1f}%"
    if roe is not None:
        key_metrics["roe"] = f"{roe*100:.1f}%"
    if rev_growth is not None:
        key_metrics["revenue_growth"] = f"{rev_growth*100:.1f}%"
    if de_raw is not None:
        key_metrics["debt_equity"] = f"{de_raw/100:.2f}x"
    if pe is not None:
        key_metrics["pe_ratio"] = f"{pe:.1f}x"
    if pb is not None:
        key_metrics["price_to_book"] = f"{pb:.1f}x"
    if profit_margin is not None:
        key_metrics["profit_margin"] = f"{profit_margin*100:.1f}%"
    if div_yield and div_yield > 0:
        key_metrics["dividend_yield"] = f"{div_yield*100:.1f}%"

    return {
        "fundamental_score": total,
        "grade": grade,
        "breakdown": {k: v[1] for k, v in breakdown.items()},
        "warnings": warnings,
        "key_metrics": key_metrics,
    }


# ── Data fetcher + cache ─────────────────────────────────────────────────────

async def _fetch_yf_data(ticker: str, market: str) -> tuple[dict[str, Any], Optional[float]]:
    """
    Fetch yfinance info dict and 5-year CAGR.
    Runs blocking yfinance calls in a thread pool.
    Returns (info_dict, five_yr_cagr).
    """
    import yfinance as yf

    suffix = ".NS" if market == "india" and not ticker.endswith((".NS", ".BO")) else ""
    yt = yf.Ticker(f"{ticker}{suffix}")

    info: dict[str, Any] = {}
    five_yr_cagr: Optional[float] = None

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(lambda: yt.info),
            timeout=15.0,
        )
    except Exception as exc:
        log.warning("fundamental_scoring.info_fetch_failed", ticker=ticker, error=str(exc))

    try:
        hist = await asyncio.wait_for(
            asyncio.to_thread(lambda: yt.history(period="5y")),
            timeout=20.0,
        )
        if hist is not None and not hist.empty and len(hist) >= 252:
            start = float(hist["Close"].iloc[0])
            end   = float(hist["Close"].iloc[-1])
            years = len(hist) / 252.0
            if start > 0:
                five_yr_cagr = (end / start) ** (1.0 / years) - 1.0
    except Exception as exc:
        log.warning("fundamental_scoring.history_fetch_failed", ticker=ticker, error=str(exc))

    return info, five_yr_cagr


async def get_fundamental_score(
    ticker: str,
    market: str,
    risk_profile: str,
    cache: CacheBackend,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch, score, and cache fundamental data for a single ticker.

    Cache key is per-ticker + market (not risk_profile) — we cache the raw
    metrics and re-score for each profile on the fly. The score key carries
    _SCORE_CACHE_VERSION so a scoring-logic change invalidates stale scores.

    refresh=True bypasses both caches and re-fetches live data from yfinance.
    """
    raw_key   = f"fundamentals:raw:{market}:{ticker}"
    score_key = f"fundamentals:score:{_SCORE_CACHE_VERSION}:{market}:{ticker}:{risk_profile}"

    # Check if score for this profile is already cached
    if not refresh:
        cached_score = await cache.get(score_key)
        if cached_score:
            log.info("fundamental_scoring.cache_hit", ticker=ticker, profile=risk_profile)
            return cached_score

    # Check if raw metrics are cached (avoids yfinance re-fetch). On refresh we
    # always re-fetch so the user gets live numbers.
    raw = None if refresh else await cache.get(raw_key)
    if raw:
        info         = raw["info"]
        five_yr_cagr = raw["five_yr_cagr"]
    else:
        log.info("fundamental_scoring.fetch", ticker=ticker, market=market, refresh=refresh)
        info, five_yr_cagr = await _fetch_yf_data(ticker, market)
        await cache.set(raw_key, {"info": info, "five_yr_cagr": five_yr_cagr}, _CACHE_TTL)

    result = compute_fundamental_score(info, five_yr_cagr, market, risk_profile)
    await cache.set(score_key, result, _CACHE_TTL)
    return result


async def enrich_candidates_with_fundamentals(
    candidates: list[dict],
    market: str,
    risk_profile: str,
    cache: CacheBackend,
    max_concurrent: int = 5,
) -> list[dict]:
    """
    Fetch fundamental scores for a list of candidate dicts in parallel.
    Updates each dict in place with 'fundamental_score', 'grade', 'warnings', 'key_metrics'.
    Failures are logged and silently skipped (candidate keeps original data).
    """
    sem = asyncio.Semaphore(max_concurrent)

    async def _enrich_one(candidate: dict) -> None:
        ticker = candidate.get("ticker", "")
        if not ticker:
            return
        async with sem:
            try:
                result = await get_fundamental_score(ticker, market, risk_profile, cache)
                candidate["fundamental_score"] = result["fundamental_score"]
                candidate["grade"]             = result["grade"]
                candidate["warnings"]          = result["warnings"]
                candidate["key_metrics"]       = result["key_metrics"]
            except Exception as exc:
                log.warning(
                    "fundamental_scoring.enrich_failed",
                    ticker=ticker,
                    error=str(exc),
                )

    await asyncio.gather(*[_enrich_one(c) for c in candidates], return_exceptions=True)
    return candidates
