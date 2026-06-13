"""
fund_metrics — pure NAV-series math for mutual-fund analysis (advisor-grade v2).

Everything here is deterministic and network-free so it can be unit-tested
directly. A NAV series is a list of floats ordered OLDEST → NEWEST (business-daily).

What we derive from NAV alone (mfapi gives no AUM / expense / holdings):
  • Rolling returns: 1m, 3m, 6m, 1y                (point-to-point %)
  • CAGR: 3y, 5y, since-inception                  (annualised %)
  • Annualised volatility, Sharpe, max drawdown    (trailing-3y window)
  • Return DECAY: recent 1y annualised vs long-term CAGR  (saturation proxy)
  • CLOSET-INDEX metrics vs a benchmark series      (active return, correlation)
  • Category-relative PERCENTILE ranking            (fair cross-fund scoring)

Design notes
────────────
• Risk metrics use a TRAILING-3y window so a long-track-record fund isn't
  penalised for surviving the 2020/2008 crashes.
• Young funds are NOT excluded: missing long-horizon metrics rank NEUTRAL
  (50th percentile), so a 1-year-old fund is judged on what it has, not zeroed.
• Scoring is CATEGORY-RELATIVE (percentile vs peers), because a 12% CAGR is poor
  for small-cap but good for large-cap.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, TypedDict

# India risk-free proxy (≈ 10-yr G-Sec). Used for Sharpe.
_RISK_FREE_RATE = 0.065
_TRADING_DAYS_PER_YEAR = 252

# Point-to-point lookback offsets, in trading days.
_OFFSET_1M = 21
_OFFSET_3M = 63
_OFFSET_6M = 126
_OFFSET_1Y = 252
_OFFSET_2Y = 504
_OFFSET_3Y = 756
_OFFSET_5Y = 1260


class FundMetrics(TypedDict, total=False):
    returns_1m: Optional[float]
    returns_3m: Optional[float]
    returns_6m: Optional[float]
    returns_1y: Optional[float]
    returns_3y_cagr: Optional[float]
    returns_5y_cagr: Optional[float]
    since_inception_cagr: Optional[float]
    volatility: Optional[float]
    sharpe: Optional[float]
    max_drawdown: Optional[float]
    decay_decel: Optional[float]    # recent 1y annualised − 3y CAGR (negative = decaying)
    history_points: int             # number of NAV observations


# ── Point-to-point helpers ────────────────────────────────────────────────────

def _point_return(navs: list[float], offset: int) -> Optional[float]:
    """Simple % return between the NAV `offset` trading days ago and the latest."""
    if len(navs) <= offset:
        return None
    past = navs[-1 - offset]
    latest = navs[-1]
    if past <= 0:
        return None
    return round((latest / past - 1) * 100, 2)


def _window_return(navs: list[float], start_offset: int, end_offset: int) -> Optional[float]:
    """% return between two trading-day offsets ago (start older than end)."""
    if len(navs) <= start_offset:
        return None
    start = navs[-1 - start_offset]
    end = navs[-1 - end_offset]
    if start <= 0:
        return None
    return round((end / start - 1) * 100, 2)


def _cagr(navs: list[float], offset: int, years: float) -> Optional[float]:
    """Annualised % growth between the NAV `offset` days ago and the latest."""
    if len(navs) <= offset or years <= 0:
        return None
    past = navs[-1 - offset]
    latest = navs[-1]
    if past <= 0 or latest <= 0:
        return None
    return round(((latest / past) ** (1.0 / years) - 1) * 100, 2)


def since_inception_cagr(navs: list[float]) -> Optional[float]:
    """Annualised return over the full available series (years ≈ points / 252)."""
    if len(navs) < 30:
        return None
    years = (len(navs) - 1) / _TRADING_DAYS_PER_YEAR
    if years <= 0:
        return None
    first, latest = navs[0], navs[-1]
    if first <= 0 or latest <= 0:
        return None
    return round(((latest / first) ** (1.0 / years) - 1) * 100, 2)


# ── Risk ──────────────────────────────────────────────────────────────────────

def annualised_volatility(navs: list[float]) -> Optional[float]:
    """Std of daily simple returns, annualised by √252. Returns % (e.g. 14.2)."""
    if len(navs) < 30:
        return None
    daily: list[float] = []
    for i in range(1, len(navs)):
        prev = navs[i - 1]
        if prev > 0:
            daily.append(navs[i] / prev - 1)
    if len(daily) < 2:
        return None
    mean = sum(daily) / len(daily)
    var = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
    std = math.sqrt(var)
    return round(std * math.sqrt(_TRADING_DAYS_PER_YEAR) * 100, 2)


def sharpe_ratio(
    annual_return_pct: Optional[float],
    volatility_pct: Optional[float],
    risk_free: float = _RISK_FREE_RATE,
) -> Optional[float]:
    """(annual return − risk-free) ÷ volatility. Inputs in %; rf as a decimal."""
    if annual_return_pct is None or volatility_pct is None or volatility_pct <= 0:
        return None
    excess = (annual_return_pct / 100.0) - risk_free
    return round(excess / (volatility_pct / 100.0), 2)


def max_drawdown(navs: list[float]) -> Optional[float]:
    """Worst peak-to-trough decline over the series. Returns % (negative, e.g. -32.1)."""
    if len(navs) < 2:
        return None
    peak = navs[0]
    worst = 0.0
    for v in navs:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return round(worst * 100, 2)


# ── Saturation / decay proxy ──────────────────────────────────────────────────

def decay_decel(navs: list[float]) -> Optional[float]:
    """
    Return-decay signal: most-recent 1-year return minus the 3-year CAGR.

    A fund whose recent annualised return has dropped well below its own longer-
    term CAGR is showing the fingerprint of AUM saturation / style drift / fading
    edge. Strongly negative (e.g. ≤ −8) is a yellow-to-red flag.
    Returns None if there isn't ≥3y of history to compare against.
    """
    r1y = _point_return(navs, _OFFSET_1Y)
    cagr3 = _cagr(navs, _OFFSET_3Y, 3.0)
    if r1y is None or cagr3 is None:
        return None
    return round(r1y - cagr3, 2)


# ── Closet-index detection (vs a benchmark NAV series) ────────────────────────

def _parse_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d, "%d-%m-%Y")
    except (ValueError, TypeError):
        return None


class ClosetMetrics(TypedDict, total=False):
    active_return: Optional[float]   # fund CAGR − benchmark CAGR over common window (pp)
    correlation: Optional[float]     # daily-return correlation with benchmark
    common_points: int


def closet_metrics(
    fund_dated: list[tuple[str, float]],
    bench_dated: list[tuple[str, float]],
    window_days: int = _OFFSET_3Y,
) -> ClosetMetrics:
    """
    Align a fund's dated NAV series with a benchmark's over their common dates and
    compute active return (alpha vs the passive alternative) and daily-return
    correlation. Both inputs are oldest→newest [(DD-MM-YYYY, nav), …].

    Low active return + high correlation ⇒ the active fund is hugging its index
    (a closet indexer) — you're paying for alpha and getting beta.
    """
    if not fund_dated or not bench_dated:
        return {"active_return": None, "correlation": None, "common_points": 0}

    bench_map = {d: v for d, v in bench_dated if v > 0}
    # Restrict the fund to its trailing window, then keep dates present in both.
    fund_window = fund_dated[-(window_days + 1):] if len(fund_dated) > window_days else fund_dated
    pairs: list[tuple[datetime, float, float]] = []
    for d, fv in fund_window:
        bv = bench_map.get(d)
        if bv is not None and fv > 0:
            dt = _parse_date(d)
            if dt is not None:
                pairs.append((dt, fv, bv))
    if len(pairs) < 60:
        return {"active_return": None, "correlation": None, "common_points": len(pairs)}

    pairs.sort(key=lambda p: p[0])
    span_years = (pairs[-1][0] - pairs[0][0]).days / 365.25
    f0, f1 = pairs[0][1], pairs[-1][1]
    b0, b1 = pairs[0][2], pairs[-1][2]

    active: Optional[float] = None
    if span_years > 0 and f0 > 0 and b0 > 0:
        fund_cagr = (f1 / f0) ** (1 / span_years) - 1
        bench_cagr = (b1 / b0) ** (1 / span_years) - 1
        active = round((fund_cagr - bench_cagr) * 100, 2)

    # Daily-return correlation
    fr, br = [], []
    for i in range(1, len(pairs)):
        pf, pb = pairs[i - 1][1], pairs[i - 1][2]
        if pf > 0 and pb > 0:
            fr.append(pairs[i][1] / pf - 1)
            br.append(pairs[i][2] / pb - 1)
    corr = _correlation(fr, br)

    return {"active_return": active, "correlation": corr, "common_points": len(pairs)}


def _correlation(a: list[float], b: list[float]) -> Optional[float]:
    n = len(a)
    if n < 2 or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    return round(cov / math.sqrt(va * vb), 3)


# ── Category-relative percentile ranking ──────────────────────────────────────

def percentile_ranks(
    values: list[Optional[float]], higher_is_better: bool = True
) -> list[float]:
    """
    Map a list of values to 0-100 percentile ranks (ties share the average rank).
    None values rank NEUTRAL (50) so funds missing a metric are neither rewarded
    nor punished on that axis — the key to judging young funds fairly.
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out = [50.0] * len(values)
    if len(present) <= 1:
        return out
    vs = [v for _, v in present]
    n = len(vs)
    for i, v in present:
        if higher_is_better:
            worse = sum(1 for x in vs if x < v)
        else:
            worse = sum(1 for x in vs if x > v)
        equal = sum(1 for x in vs if x == v) - 1
        out[i] = round((worse + 0.5 * equal) / (n - 1) * 100, 1)
    return out


# ── Per-fund metric bundle ────────────────────────────────────────────────────

def compute_metrics(navs: list[float]) -> FundMetrics:
    """Compute the full metric set from a NAV series ordered oldest → newest."""
    if not navs:
        return {}

    r1y = _point_return(navs, _OFFSET_1Y)
    cagr3 = _cagr(navs, _OFFSET_3Y, 3.0)
    cagr5 = _cagr(navs, _OFFSET_5Y, 5.0)
    si = since_inception_cagr(navs)

    # Trailing ~3y window for risk metrics (fall back to full history if shorter).
    window = navs[-(_OFFSET_3Y + 1):] if len(navs) > _OFFSET_3Y else navs
    vol = annualised_volatility(window)
    annual_return = cagr3 if cagr3 is not None else (r1y if r1y is not None else si)

    return {
        "returns_1m":           _point_return(navs, _OFFSET_1M),
        "returns_3m":           _point_return(navs, _OFFSET_3M),
        "returns_6m":           _point_return(navs, _OFFSET_6M),
        "returns_1y":           r1y,
        "returns_3y_cagr":      cagr3,
        "returns_5y_cagr":      cagr5,
        "since_inception_cagr": si,
        "volatility":           vol,
        "sharpe":               sharpe_ratio(annual_return, vol),
        "max_drawdown":         max_drawdown(window),
        "decay_decel":          decay_decel(navs),
        "history_points":       len(navs),
    }


def track_record_tier(history_points: int) -> str:
    """established (≥3y) · emerging (1-3y) · new (<1y), from NAV-observation count."""
    years = history_points / _TRADING_DAYS_PER_YEAR
    if years >= 3:
        return "established"
    if years >= 1:
        return "emerging"
    return "new"


# ── Absolute fallback score (used for tiny category cohorts) ──────────────────

def score_fund(m: FundMetrics) -> tuple[float, str]:
    """
    Composite 0-100 "should I enter now" score → entry signal, using ABSOLUTE
    thresholds. Used as a fallback when a category has too few peers for stable
    percentile ranking. Category-relative scoring (in fund_data) is preferred.

    ≥65 → strong_entry · 40-64 → watch · <40 → avoid
    """
    score = 0.0

    sharpe = m.get("sharpe")
    if sharpe is not None:
        if   sharpe >= 1.5: score += 28
        elif sharpe >= 1.0: score += 23
        elif sharpe >= 0.6: score += 16
        elif sharpe >= 0.3: score += 9
        elif sharpe >= 0.0: score += 4
    cagr3 = m.get("returns_3y_cagr")
    if cagr3 is not None:
        if   cagr3 >= 18: score += 17
        elif cagr3 >= 12: score += 13
        elif cagr3 >= 8:  score += 9
        elif cagr3 >= 4:  score += 4

    r3m = m.get("returns_3m")
    if r3m is not None:
        if   8 <= r3m <= 20:  score += 18
        elif 3 <= r3m < 8:    score += 13
        elif 20 < r3m <= 35:  score += 10
        elif 0 <= r3m < 3:    score += 7
        elif r3m > 35:        score += 4
        else:                 score += 2
    r6m = m.get("returns_6m")
    if r6m is not None:
        if   r6m >= 10: score += 12
        elif r6m >= 3:  score += 8
        elif r6m >= -5: score += 4

    mdd = m.get("max_drawdown")
    if mdd is not None:
        depth = abs(mdd)
        if   depth <= 15: score += 15
        elif depth <= 25: score += 11
        elif depth <= 35: score += 7
        elif depth <= 50: score += 3

    r1m = m.get("returns_1m")
    if r1m is not None:
        if   r1m >= 2:   score += 10
        elif r1m >= -2:  score += 7
        elif r1m >= -6:  score += 3

    score = round(min(score, 100.0), 1)
    signal = "strong_entry" if score >= 65 else "watch" if score >= 40 else "avoid"
    return score, signal


# ── Plain-English reasoning (mock mode + AI fallback) ─────────────────────────

def build_entry_reason(
    *,
    category: Optional[str],
    signal: str,
    track_record: str,
    m: FundMetrics,
    active_return: Optional[float] = None,
    is_closet: bool = False,
    is_decaying: bool = False,
    is_discovery: bool = False,
) -> str:
    """Heuristic 1-2 line reasoning grounded in the metrics and rule-out flags."""
    cagr3 = m.get("returns_3y_cagr")
    si = m.get("since_inception_cagr")
    sharpe = m.get("sharpe")
    r6m = m.get("returns_6m")

    # Rule-outs lead — they override the headline.
    if is_closet:
        a = f"{active_return:+.1f}pp" if active_return is not None else "negligible"
        return (
            f"Closet indexer — only {a} of return over its benchmark while hugging it closely. "
            "You're paying active fees for near-index performance; the passive option is cheaper."
        )
    if is_decaying:
        d = m.get("decay_decel")
        gap = f"{d:.0f}pp below" if d is not None else "well below"
        return (
            f"Fading edge — recent 1-year return is {gap} its 3-year CAGR, a classic sign of "
            "AUM bloat or style drift. Past performance here is flattering the present."
        )

    # Quality stats line.
    bits: list[str] = []
    headline_cagr = cagr3 if cagr3 is not None else si
    if headline_cagr is not None:
        label = "3yr CAGR" if cagr3 is not None else "since-inception CAGR"
        bits.append(f"{headline_cagr:.0f}% {label}")
    if sharpe is not None:
        bits.append(f"{sharpe:.2f} Sharpe")
    if active_return is not None:
        bits.append(f"{active_return:+.0f}pp vs benchmark")
    stats = ", ".join(bits) if bits else "limited history"

    if is_discovery:
        return (
            f"Discovery — this {track_record} fund already ranks near the top of its {category or 'category'} peers "
            f"({stats}). Less track record, but the early signal is strong; size it as a satellite, not a core."
        )
    if signal == "strong_entry":
        lead = f"Top-quartile in {category or 'its category'} on risk-adjusted returns"
    elif signal == "avoid":
        lead = f"Lags its {category or 'category'} peers — better options exist in the same bucket"
    else:
        lead = f"Middle-of-the-pack for {category or 'its category'} — fine to hold, no urgency to enter"

    momentum = f" 6-month move is {r6m:+.0f}%." if r6m is not None else ""
    return f"{lead} ({stats})." + momentum
