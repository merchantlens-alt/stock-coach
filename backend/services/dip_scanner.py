"""
DipScannerService — finds quality stocks that have pulled back from recent highs
and may be worth buying as the decline looks technical, not fundamental.

Algorithm
─────────
1. Download 3-month daily OHLCV for the entire universe via yf.download (one call).
2. Compute % below 3-month high for each ticker.
3. Filter: down 8–45% from 3-month high, price > $5, volume > 200 K.
4. Batch-fetch analyst consensus + fundamentals for the ~15-25 filtered tickers.
5. Compute dip_score (0–100): RSI + analyst quality + dip magnitude + revenue growth.
6. Label: score ≥ 60 = "prime", 35–59 = "watch". Below 35 = discarded.
7. Sort by score desc, return top 15.

Cache TTL: 60 min — dip opportunities don't change minute-to-minute, but stale
overnight data would be unhelpful so we don't go longer than an hour.

What makes a GOOD dip vs a FALLING KNIFE:
  Good: RSI oversold (<40) + analyst consensus BUY + revenue still growing
        + decline caused by macro/sector, not company-specific bad news
  Bad:  RSI still high (50+) after decline, analyst consensus HOLD/SELL,
        revenue declining, earnings miss in recent news
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Any, Optional

from core.config import Settings
from core.logging import get_logger
from models.schemas import DipQuality, DipScanResponse, DipStock, Market
from services.market_data import _US_TICKER_UNIVERSE, _INDIA_TICKER_UNIVERSE

log = get_logger(__name__)

# ── Analyst consensus → quality score mapping ─────────────────────────────────

_CONSENSUS_SCORE: dict[str, int] = {
    "strong_buy":   35,
    "buy":          30,
    "outperform":   22,
    "overweight":   22,
    "hold":         10,
    "neutral":      10,
    "underperform":  0,
    "underweight":   0,
    "sell":          0,
    "strong_sell":   0,
}

_CONSENSUS_SKIP = {"underperform", "underweight", "sell", "strong_sell"}


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Simple RSI from a list of close prices (oldest first)."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains  = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _compute_dip_score(
    rsi: Optional[float],
    consensus: Optional[str],
    pct_from_high: float,     # negative, e.g. -18.4
    upside_to_target: Optional[float],
    revenue_growth: Optional[float],
) -> float:
    score = 0.0

    # ── RSI component (40 pts max) ─────────────────────────────────────────────
    if rsi is not None:
        if rsi < 25:   score += 40
        elif rsi < 30: score += 36
        elif rsi < 35: score += 30
        elif rsi < 40: score += 22
        elif rsi < 45: score += 14
        elif rsi < 50: score += 8
        else:          score += 3

    # ── Analyst quality component (35 pts max) ────────────────────────────────
    if consensus:
        score += _CONSENSUS_SCORE.get(consensus.lower().replace(" ", "_").replace("-", "_"), 0)
    # Bonus: meaningful upside to analyst target
    if upside_to_target is not None:
        if upside_to_target >= 30: score += 5
        elif upside_to_target >= 20: score += 3

    # ── Dip magnitude component (20 pts max) ──────────────────────────────────
    # Sweet spot: 12–30% below recent high (meaningful but not a collapse)
    depth = abs(pct_from_high)
    if   12 <= depth <= 20: score += 20
    elif 20 < depth <= 30:  score += 16
    elif 8  <= depth < 12:  score += 12
    elif 30 < depth <= 40:  score += 10  # deeper — more risk, less score
    elif 40 < depth <= 45:  score +=  5

    # ── Fundamental quality bonus (5 pts max) ─────────────────────────────────
    if revenue_growth is not None:
        if revenue_growth >= 0.15: score += 5
        elif revenue_growth >= 0.05: score += 2

    return round(min(score, 100), 1)


def _dip_reason(
    pct_from_high: float,
    change_1d: float,
    consensus: Optional[str],
) -> str:
    """Quick heuristic reason for the dip — AI analysis will refine this."""
    depth = abs(pct_from_high)
    if depth > 30:
        return "Significant pullback — verify no fundamental deterioration"
    if change_1d > -1 and depth > 10:
        return "Gradual sector rotation or profit-taking"
    if change_1d < -5:
        return "Broad market/sector selloff"
    return "Technical pullback — no clear negative catalyst found"


class DipScannerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def scan(self, market: Market) -> DipScanResponse:
        if market == "us":
            dips = await self._scan_us()
        else:
            dips = await self._scan_india()
        return DipScanResponse(
            market=market,
            dips=dips[:15],
            scanned_at=datetime.utcnow(),
        )

    # ── US scan ───────────────────────────────────────────────────────────────

    async def _scan_us(self) -> list[DipStock]:
        import yfinance as yf
        import pandas as pd

        tickers_str = " ".join(_US_TICKER_UNIVERSE.keys())
        try:
            df: pd.DataFrame = await asyncio.to_thread(
                yf.download,
                tickers_str,
                period="3mo",
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("dip_scanner.yf_download_failed", market="us", error=str(exc))
            return []

        if df.empty or len(df) < 10:
            return []

        # ── Compute dip candidates from OHLCV history ─────────────────────────
        candidates: list[dict] = []
        for ticker, meta in _US_TICKER_UNIVERSE.items():
            try:
                close_series = df["Close"][ticker].dropna()
                high_series  = df["High"][ticker].dropna()
                vol_series   = df["Volume"][ticker].dropna()

                if len(close_series) < 15:
                    continue

                current    = float(close_series.iloc[-1])
                three_m_hi = float(high_series.max())
                avg_vol    = int(vol_series.mean()) if not vol_series.empty else 0
                last_vol   = int(vol_series.iloc[-1]) if not vol_series.empty else 0
                change_1d  = float((close_series.iloc[-1] - close_series.iloc[-2]) / close_series.iloc[-2] * 100) if len(close_series) >= 2 else 0.0

                # Filter: meaningful price, volume, and dip magnitude
                if current < 5 or avg_vol < 200_000:
                    continue
                if three_m_hi <= 0:
                    continue
                pct_from_high = round((current - three_m_hi) / three_m_hi * 100, 2)
                if pct_from_high >= -8 or pct_from_high < -45:
                    continue  # not enough dip, or likely a falling knife

                rsi_val = _rsi(list(close_series.values))
                candidates.append({
                    "ticker":         ticker,
                    "meta":           meta,
                    "price":          round(current, 2),
                    "change_1d":      round(change_1d, 2),
                    "pct_from_high":  pct_from_high,
                    "three_m_hi":     round(three_m_hi, 2),
                    "rsi":            rsi_val,
                    "avg_vol":        avg_vol,
                    "last_vol":       last_vol,
                    "closes":         list(close_series.values),
                })
            except Exception:
                continue

        if not candidates:
            return []

        log.info("dip_scanner.us_candidates", count=len(candidates))

        # ── Batch-fetch fundamentals for candidates ───────────────────────────
        fund_map = await self._batch_fundamentals(
            [c["ticker"] for c in candidates], market="us"
        )

        # ── Score + filter + sort ─────────────────────────────────────────────
        dips: list[DipStock] = []
        for c in candidates:
            ticker   = c["ticker"]
            fund     = fund_map.get(ticker, {})
            consensus = fund.get("consensus")

            # Hard gate: analyst consensus must not be sell/underperform
            if consensus and consensus.lower().replace(" ", "_").replace("-", "_") in _CONSENSUS_SKIP:
                continue

            analyst_target    = _safe_float(fund.get("target"))
            upside_to_target  = None
            if analyst_target and c["price"] > 0:
                upside_to_target = round((analyst_target - c["price"]) / c["price"] * 100, 1)

            # Only show stocks where analyst target is ABOVE current price (i.e. upside exists)
            if upside_to_target is not None and upside_to_target < 5:
                continue

            revenue_growth = _safe_float(fund.get("revenue_growth"))
            score = _compute_dip_score(
                rsi=c["rsi"],
                consensus=consensus,
                pct_from_high=c["pct_from_high"],
                upside_to_target=upside_to_target,
                revenue_growth=revenue_growth,
            )
            if score < 35:
                continue

            quality: DipQuality = "prime" if score >= 60 else "watch"
            hi_52 = _safe_float(fund.get("hi_52"))
            lo_52 = _safe_float(fund.get("lo_52"))
            pct_of_range: Optional[float] = None
            if hi_52 and lo_52 and hi_52 > lo_52:
                pct_of_range = round((c["price"] - lo_52) / (hi_52 - lo_52) * 100, 1)

            dips.append(DipStock(
                ticker=ticker,
                name=c["meta"]["name"],
                market="us",
                sector=c["meta"].get("sector"),
                price=c["price"],
                change_pct_1d=c["change_1d"],
                change_pct_from_high=c["pct_from_high"],
                three_month_high=c["three_m_hi"],
                fifty_two_week_high=hi_52,
                fifty_two_week_low=lo_52,
                pct_of_52w_range=pct_of_range,
                rsi_14=c["rsi"],
                analyst_consensus=consensus,
                analyst_target=analyst_target,
                upside_to_target=upside_to_target,
                revenue_growth_yoy=revenue_growth,
                dip_quality=quality,
                dip_score=score,
                dip_reason=_dip_reason(c["pct_from_high"], c["change_1d"], consensus),
                avg_volume=c["avg_vol"],
            ))

        dips.sort(key=lambda d: d.dip_score, reverse=True)
        log.info("dip_scanner.us_done", prime=sum(1 for d in dips if d.dip_quality == "prime"), total=len(dips))
        return dips

    # ── India scan ────────────────────────────────────────────────────────────

    async def _scan_india(self) -> list[DipStock]:
        import yfinance as yf
        import pandas as pd

        yf_tickers = {f"{t}.NS": (t, meta) for t, meta in _INDIA_TICKER_UNIVERSE.items()}
        tickers_str = " ".join(yf_tickers.keys())

        try:
            df: pd.DataFrame = await asyncio.to_thread(
                yf.download,
                tickers_str,
                period="3mo",
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("dip_scanner.yf_download_failed", market="india", error=str(exc))
            return []

        if df.empty or len(df) < 10:
            return []

        candidates: list[dict] = []
        for yf_sym, (ticker, meta) in yf_tickers.items():
            try:
                close_series = df["Close"][yf_sym].dropna()
                high_series  = df["High"][yf_sym].dropna()
                vol_series   = df["Volume"][yf_sym].dropna()
                if len(close_series) < 15:
                    continue
                current    = float(close_series.iloc[-1])
                three_m_hi = float(high_series.max())
                avg_vol    = int(vol_series.mean()) if not vol_series.empty else 0
                change_1d  = float((close_series.iloc[-1] - close_series.iloc[-2]) / close_series.iloc[-2] * 100) if len(close_series) >= 2 else 0.0

                if current < 50 or avg_vol < 100_000 or three_m_hi <= 0:
                    continue
                pct_from_high = round((current - three_m_hi) / three_m_hi * 100, 2)
                if pct_from_high >= -8 or pct_from_high < -45:
                    continue

                rsi_val = _rsi(list(close_series.values))
                candidates.append({
                    "ticker": ticker, "meta": meta, "price": round(current, 2),
                    "change_1d": round(change_1d, 2), "pct_from_high": pct_from_high,
                    "three_m_hi": round(three_m_hi, 2), "rsi": rsi_val,
                    "avg_vol": avg_vol, "yf_sym": yf_sym,
                })
            except Exception:
                continue

        if not candidates:
            return []

        fund_map = await self._batch_fundamentals(
            [c["ticker"] for c in candidates], market="india"
        )

        dips: list[DipStock] = []
        for c in candidates:
            ticker   = c["ticker"]
            fund     = fund_map.get(ticker, {})
            consensus = fund.get("consensus")
            if consensus and consensus.lower().replace(" ", "_") in _CONSENSUS_SKIP:
                continue
            analyst_target = _safe_float(fund.get("target"))
            upside_to_target = None
            if analyst_target and c["price"] > 0:
                upside_to_target = round((analyst_target - c["price"]) / c["price"] * 100, 1)
            if upside_to_target is not None and upside_to_target < 5:
                continue
            score = _compute_dip_score(
                rsi=c["rsi"], consensus=consensus,
                pct_from_high=c["pct_from_high"],
                upside_to_target=upside_to_target,
                revenue_growth=_safe_float(fund.get("revenue_growth")),
            )
            if score < 35:
                continue
            quality: DipQuality = "prime" if score >= 60 else "watch"
            hi_52 = _safe_float(fund.get("hi_52"))
            lo_52 = _safe_float(fund.get("lo_52"))
            pct_of_range = None
            if hi_52 and lo_52 and hi_52 > lo_52:
                pct_of_range = round((c["price"] - lo_52) / (hi_52 - lo_52) * 100, 1)
            dips.append(DipStock(
                ticker=ticker, name=c["meta"]["name"], market="india",
                sector=c["meta"].get("sector"),
                price=c["price"], change_pct_1d=c["change_1d"],
                change_pct_from_high=c["pct_from_high"],
                three_month_high=c["three_m_hi"],
                fifty_two_week_high=hi_52, fifty_two_week_low=lo_52,
                pct_of_52w_range=pct_of_range, rsi_14=c["rsi"],
                analyst_consensus=consensus, analyst_target=analyst_target,
                upside_to_target=upside_to_target,
                revenue_growth_yoy=_safe_float(fund.get("revenue_growth")),
                dip_quality=quality, dip_score=score,
                dip_reason=_dip_reason(c["pct_from_high"], c["change_1d"], consensus),
                avg_volume=c["avg_vol"],
            ))

        dips.sort(key=lambda d: d.dip_score, reverse=True)
        return dips

    # ── Batch fundamentals ────────────────────────────────────────────────────

    async def _batch_fundamentals(
        self, tickers: list[str], market: str
    ) -> dict[str, dict]:
        """
        Fetch analyst consensus, target price, 52-week range, and revenue growth
        for all candidate tickers in parallel.  Returns {} on per-ticker failure.
        """
        async def _fetch_one(ticker: str) -> tuple[str, dict]:
            import yfinance as yf
            yf_sym = f"{ticker}.NS" if market == "india" else ticker
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(lambda s=yf_sym: yf.Ticker(s).info),
                    timeout=8.0,
                )
                return ticker, {
                    "consensus":      info.get("recommendationKey"),
                    "target":         _safe_float(info.get("targetMeanPrice")),
                    "hi_52":          _safe_float(info.get("fiftyTwoWeekHigh")),
                    "lo_52":          _safe_float(info.get("fiftyTwoWeekLow")),
                    "revenue_growth": _safe_float(info.get("revenueGrowth")),
                }
            except Exception:
                return ticker, {}

        results = await asyncio.gather(
            *[_fetch_one(t) for t in tickers],
            return_exceptions=True,
        )
        return {
            ticker: data
            for result in results
            if not isinstance(result, Exception)
            for ticker, data in [result]
        }
