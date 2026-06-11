"""
ValueRecoveryScannerService — finds stocks where valuation is compressed relative
to fundamentals and multiple inflection signals suggest a re-rating is in progress.

Algorithm
─────────
1. Download 1-year daily OHLCV for the full universe via yf.download (one batch call).
2. Apply basic filter: price > threshold, avg volume > threshold.
3. Parallel-fetch fundamentals (P/E, forward P/E, growth, ROE, margins, D/E) for
   all ~80-100 survivors via yf.Ticker.info (semaphore-limited to 8 concurrent).
4. Entry gate: stock must be profitable (P/E exists, > 0, < 50) with at least one
   valuation compression signal (cheap absolute P/E OR forward P/E contracting).
5. Inflection filter: must have ≥ 2 active recovery signals (EPS growing, revenue
   growing, P/E contracting, strong ROE, low debt, profitable, analyst bullish).
6. Score 0-100 on valuation depth × signal count × growth quality × analyst view.
7. Label: score ≥ 65 = "strong", 40-64 = "emerging". Below 40 discarded.
8. Sort by score desc, return top 15.

Cache TTL: 2 hours — fundamental metrics change daily at best; no need for
the 1-hour refresh cadence of the price-driven Dip Scanner.

What makes a GOOD value recovery vs a VALUE TRAP:
  Good: forward P/E contracting + EPS growing + revenue growing + ROE improving
        → market hasn't priced in the earnings acceleration yet
  Bad:  cheap P/E but earnings declining, margins collapsing, or analyst SELL rating
        → cheap for a reason; fundamentals getting worse, not better
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime
from typing import Any, Optional

from core.config import Settings
from core.logging import get_logger
from models.schemas import (
    Market,
    RecoveryQuality,
    RecoverySignal,
    ValueRecoveryScanResponse,
    ValueRecoveryStock,
)
from services.market_data import _INDIA_TICKER_UNIVERSE, _US_TICKER_UNIVERSE

log = get_logger(__name__)

_CONSENSUS_SKIP    = {"underperform", "underweight", "sell", "strong_sell"}
_CONSENSUS_BULLISH = {"strong_buy", "buy", "outperform", "overweight"}


# ── Pure helpers (fully testable without I/O) ─────────────────────────────────

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


def _norm_consensus(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return raw.lower().replace(" ", "_").replace("-", "_")


def classify_signals(
    pe: Optional[float],
    forward_pe: Optional[float],
    earnings_growth: Optional[float],
    revenue_growth: Optional[float],
    roe: Optional[float],
    de_ratio: Optional[float],
    profit_margin: Optional[float],
    consensus: Optional[str],
) -> list[RecoverySignal]:
    """
    Return the list of active inflection signals for a stock.

    All numeric thresholds use yfinance's unit conventions:
      - earnings_growth, revenue_growth, roe, profit_margin: decimal (0.15 = 15%)
      - de_ratio: percentage as reported by yfinance (80 = 0.8× actual D/E)
      - pe, forward_pe: raw P/E multiples
    """
    signals: list[RecoverySignal] = []

    if earnings_growth is not None and earnings_growth > 0.08:
        signals.append(RecoverySignal.eps_growing)

    if revenue_growth is not None and revenue_growth > 0.05:
        signals.append(RecoverySignal.revenue_growing)

    # P/E contracting: forward earnings are substantially higher → future P/E will compress
    if (
        pe is not None
        and forward_pe is not None
        and forward_pe > 0
        and forward_pe < pe * 0.95
    ):
        signals.append(RecoverySignal.pe_contracting)

    if roe is not None and roe > 0.13:
        signals.append(RecoverySignal.strong_roe)

    # yfinance debtToEquity is in percentage units (80 = 0.8× actual D/E)
    if de_ratio is not None and de_ratio < 80:
        signals.append(RecoverySignal.low_debt)

    if profit_margin is not None and profit_margin > 0.08:
        signals.append(RecoverySignal.profitable)

    norm = _norm_consensus(consensus)
    if norm and norm in _CONSENSUS_BULLISH:
        signals.append(RecoverySignal.analyst_bullish)

    return signals


def compute_recovery_score(
    pe: Optional[float],
    forward_pe: Optional[float],
    earnings_growth: Optional[float],
    signals: list[RecoverySignal],
    consensus: Optional[str],
    upside_to_target: Optional[float],
) -> float:
    """
    Score a value recovery candidate on a 0-100 scale.

    Component breakdown:
      - Valuation (max 30): lower P/E + forward contraction bonus
      - Signals   (max 40): number of active inflection signals
      - Growth    (max 15): magnitude of earnings growth
      - Analyst   (max 15): consensus quality + upside to target
    """
    score = 0.0

    # ── Valuation component ───────────────────────────────────────────────────
    if pe is not None:
        if   pe < 12: score += 30
        elif pe < 15: score += 25
        elif pe < 18: score += 20
        elif pe < 22: score += 14
        elif pe < 28: score +=  8
        else:         score +=  3

    # Forward P/E contraction bonus (max +10 pts)
    if pe is not None and forward_pe is not None and forward_pe > 0 and forward_pe < pe:
        contraction = (1.0 - forward_pe / pe)   # 0.20 = 20% contraction
        score += min(contraction * 20.0, 10.0)

    # ── Signal count component ────────────────────────────────────────────────
    n = len(signals)
    if   n >= 5: score += 40
    elif n >= 4: score += 33
    elif n >= 3: score += 25
    elif n >= 2: score += 15

    # ── Growth quality component ──────────────────────────────────────────────
    if earnings_growth is not None:
        if   earnings_growth > 0.25: score += 15
        elif earnings_growth > 0.15: score += 10
        elif earnings_growth > 0.08: score +=  6

    # ── Analyst component ─────────────────────────────────────────────────────
    norm = _norm_consensus(consensus)
    if norm:
        if   norm == "strong_buy":                          score += 10
        elif norm in {"buy", "outperform", "overweight"}:  score +=  7
        elif norm in {"hold", "neutral"}:                  score +=  2

    if upside_to_target is not None:
        if   upside_to_target >= 30: score += 5
        elif upside_to_target >= 20: score += 3
        elif upside_to_target >= 10: score += 1

    return round(min(score, 100.0), 1)


def build_recovery_thesis(
    pe: Optional[float],
    forward_pe: Optional[float],
    earnings_growth: Optional[float],
    revenue_growth: Optional[float],
    signals: list[RecoverySignal],
) -> str:
    """
    One-liner describing the re-rating thesis.
    Leads with the strongest valuation angle, then up to 2 growth signals.
    """
    parts: list[str] = []

    # Lead with the most compelling valuation angle
    if (
        pe is not None
        and forward_pe is not None
        and forward_pe > 0
        and forward_pe < pe
    ):
        pct = round((1.0 - forward_pe / pe) * 100)
        parts.append(f"P/E contracting {pct}%")
    elif pe is not None and pe < 18:
        parts.append(f"P/E {pe:.1f}× (below mkt avg)")
    elif pe is not None:
        parts.append(f"P/E {pe:.1f}×")

    # Add key growth signals
    if RecoverySignal.eps_growing in signals and earnings_growth is not None:
        parts.append(f"EPS +{earnings_growth * 100:.0f}% YoY")
    if RecoverySignal.revenue_growing in signals and revenue_growth is not None:
        parts.append(f"Rev +{revenue_growth * 100:.0f}%")
    if RecoverySignal.strong_roe in signals and RecoverySignal.eps_growing not in signals:
        parts.append("Strong ROE")
    if RecoverySignal.low_debt in signals and len(parts) < 3:
        parts.append("Deleveraged")
    if RecoverySignal.analyst_bullish in signals and len(parts) < 3:
        parts.append("Analyst Buy")

    if not parts:
        return "Multiple fundamental inflections — potential re-rating"

    core = " · ".join(parts[:3])
    return f"{core} → re-rating candidate"


# ── Scanner service ───────────────────────────────────────────────────────────

class ValueRecoveryScannerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def scan(self, market: Market) -> ValueRecoveryScanResponse:
        stocks = await (self._scan_us() if market == "us" else self._scan_india())
        return ValueRecoveryScanResponse(
            market=market,
            stocks=stocks[:15],
            scanned_at=datetime.utcnow(),
        )

    # ── US scan ───────────────────────────────────────────────────────────────

    async def _scan_us(self) -> list[ValueRecoveryStock]:
        import pandas as pd
        import yfinance as yf

        tickers_str = " ".join(_US_TICKER_UNIVERSE.keys())
        try:
            df: pd.DataFrame = await asyncio.to_thread(
                yf.download,
                tickers_str,
                period="1y",
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("value_recovery.yf_download_failed", market="us", error=str(exc))
            return []

        if df.empty or len(df) < 20:
            return []

        candidates: list[dict] = []
        for ticker, meta in _US_TICKER_UNIVERSE.items():
            try:
                close_s = df["Close"][ticker].dropna()
                vol_s   = df["Volume"][ticker].dropna()
                if len(close_s) < 20:
                    continue
                current   = float(close_s.iloc[-1])
                prev      = float(close_s.iloc[-2])
                avg_vol   = int(vol_s.mean()) if not vol_s.empty else 0
                change_1d = round((current - prev) / prev * 100, 2) if prev > 0 else 0.0
                if current < 5 or avg_vol < 300_000:
                    continue
                candidates.append({
                    "ticker": ticker, "meta": meta,
                    "price": round(current, 2), "change_1d": change_1d, "avg_vol": avg_vol,
                })
            except Exception:
                continue

        if not candidates:
            return []

        log.info("value_recovery.us_candidates", count=len(candidates))
        fund_map = await self._fetch_fundamentals_with_retry(
            [c["ticker"] for c in candidates], market="us"
        )
        return self._score_and_filter(candidates, fund_map, market="us")

    # ── India scan ────────────────────────────────────────────────────────────

    async def _scan_india(self) -> list[ValueRecoveryStock]:
        import pandas as pd
        import yfinance as yf

        yf_tickers = {f"{t}.NS": (t, meta) for t, meta in _INDIA_TICKER_UNIVERSE.items()}
        tickers_str = " ".join(yf_tickers.keys())

        try:
            df: pd.DataFrame = await asyncio.to_thread(
                yf.download,
                tickers_str,
                period="1y",
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:
            log.warning("value_recovery.yf_download_failed", market="india", error=str(exc))
            return []

        if df.empty or len(df) < 20:
            return []

        candidates: list[dict] = []
        for yf_sym, (ticker, meta) in yf_tickers.items():
            try:
                close_s = df["Close"][yf_sym].dropna()
                vol_s   = df["Volume"][yf_sym].dropna()
                if len(close_s) < 20:
                    continue
                current   = float(close_s.iloc[-1])
                prev      = float(close_s.iloc[-2])
                avg_vol   = int(vol_s.mean()) if not vol_s.empty else 0
                change_1d = round((current - prev) / prev * 100, 2) if prev > 0 else 0.0
                if current < 50 or avg_vol < 100_000:
                    continue
                candidates.append({
                    "ticker": ticker, "meta": meta,
                    "price": round(current, 2), "change_1d": change_1d, "avg_vol": avg_vol,
                })
            except Exception:
                continue

        if not candidates:
            return []

        log.info("value_recovery.india_candidates", count=len(candidates))
        fund_map = await self._fetch_fundamentals_with_retry(
            [c["ticker"] for c in candidates], market="india"
        )
        return self._score_and_filter(candidates, fund_map, market="india")

    # ── Scoring and filtering ─────────────────────────────────────────────────

    def _score_and_filter(
        self,
        candidates: list[dict],
        fund_map: dict[str, dict],
        market: str,
    ) -> list[ValueRecoveryStock]:
        results: list[ValueRecoveryStock] = []

        for c in candidates:
            ticker = c["ticker"]
            fund   = fund_map.get(ticker, {})

            pe              = _safe_float(fund.get("pe"))
            forward_pe      = _safe_float(fund.get("forward_pe"))
            earnings_growth = _safe_float(fund.get("earnings_growth"))
            revenue_growth  = _safe_float(fund.get("revenue_growth"))
            roe             = _safe_float(fund.get("roe"))
            de_ratio        = _safe_float(fund.get("de_ratio"))
            profit_margin   = _safe_float(fund.get("profit_margin"))
            consensus       = fund.get("consensus")
            analyst_target  = _safe_float(fund.get("target"))

            # ── Quality gates ──────────────────────────────────────────────────
            # Hard exclude deeply loss-making companies
            if profit_margin is not None and profit_margin < -0.10:
                continue
            # Hard exclude sell / underperform rated stocks
            if _norm_consensus(consensus) in _CONSENSUS_SKIP:
                continue

            # ── Entry gate: need a real P/E anchor ────────────────────────────
            # If trailing P/E is absent or extreme, fall back to forward P/E
            if pe is None or pe <= 0 or pe > 50:
                if forward_pe is None or forward_pe <= 0 or forward_pe > 40:
                    continue
                pe = forward_pe  # anchor on forward P/E; mark trailing as unavailable
                forward_pe = None

            # ── Entry gate: at least one valuation compression signal ──────────
            # Path A: trailing P/E is genuinely cheap (at or below market median)
            # Path B: forward P/E is contracting meaningfully AND the trailing P/E
            #         isn't an outright growth premium (cap at 35×).  A 42× trailing
            #         P/E with a 48% forward contraction is a fast-growth story, not
            #         a value recovery — the market multiple is expensive TODAY even
            #         if earnings are growing into it.
            passes_valuation = (
                pe < 22  # Path A — cheap on trailing multiple
                or (
                    pe < 35  # Path B — not a premium growth multiple
                    and forward_pe is not None
                    and forward_pe > 0
                    and forward_pe < pe * 0.90  # meaningful forward earnings growth
                )
            )
            if not passes_valuation:
                continue

            # ── Inflection signals ─────────────────────────────────────────────
            signals = classify_signals(
                pe=pe, forward_pe=forward_pe,
                earnings_growth=earnings_growth,
                revenue_growth=revenue_growth,
                roe=roe, de_ratio=de_ratio,
                profit_margin=profit_margin,
                consensus=consensus,
            )
            if len(signals) < 2:
                continue

            # ── Analyst upside ─────────────────────────────────────────────────
            upside_to_target: Optional[float] = None
            if analyst_target and c["price"] > 0:
                upside_to_target = round(
                    (analyst_target - c["price"]) / c["price"] * 100, 1
                )

            # Require meaningful re-rating room when an analyst target exists.
            # 15% minimum over 12 months filters low-conviction picks (e.g. 10%
            # upside = just market return, not a recovery play).
            # Stocks with no analyst coverage are NOT excluded — they just don't
            # receive the analyst upside bonus in the score.
            _MIN_UPSIDE = 15.0
            if upside_to_target is not None and upside_to_target < _MIN_UPSIDE:
                continue

            score = compute_recovery_score(
                pe=pe,
                forward_pe=forward_pe,
                earnings_growth=earnings_growth,
                signals=signals,
                consensus=consensus,
                upside_to_target=upside_to_target,
            )
            if score < 40:
                continue

            quality: RecoveryQuality = "strong" if score >= 65 else "emerging"

            pe_contraction_pct: Optional[float] = None
            if forward_pe is not None and forward_pe > 0 and forward_pe < pe:
                pe_contraction_pct = round((1.0 - forward_pe / pe) * 100, 1)

            results.append(ValueRecoveryStock(
                ticker=ticker,
                name=c["meta"]["name"],
                market=market,  # type: ignore[arg-type]
                sector=c["meta"].get("sector"),
                price=c["price"],
                change_pct_1d=c["change_1d"],
                pe_ratio=pe,
                forward_pe=forward_pe,
                pe_contraction_pct=pe_contraction_pct,
                signals=signals,
                recovery_quality=quality,
                recovery_score=score,
                recovery_thesis=build_recovery_thesis(
                    pe=pe,
                    forward_pe=forward_pe,
                    earnings_growth=earnings_growth,
                    revenue_growth=revenue_growth,
                    signals=signals,
                ),
                earnings_growth_yoy=earnings_growth,
                revenue_growth_yoy=revenue_growth,
                roe=roe,
                de_ratio=de_ratio,
                profit_margin=profit_margin,
                analyst_consensus=consensus,
                analyst_target=analyst_target,
                upside_to_target=upside_to_target,
                avg_volume=c["avg_vol"],
            ))

        results.sort(key=lambda s: s.recovery_score, reverse=True)
        log.info(
            "value_recovery.scan_done",
            market=market,
            strong=sum(1 for s in results if s.recovery_quality == "strong"),
            total=len(results),
        )
        return results

    # ── Fundamentals fetch with retry ────────────────────────────────────────

    async def _fetch_fundamentals_with_retry(
        self, tickers: list[str], market: str
    ) -> dict[str, dict]:
        """
        Fetch fundamentals, then do a single retry pass for any ticker that came
        back empty (yfinance rate-limit or transient timeout).  This prevents
        high-quality stocks like META from silently falling off the list just
        because their info call happened to time out in the first batch.
        """
        fund_map = await self._batch_fundamentals(tickers, market)

        failed = [t for t in tickers if not fund_map.get(t)]
        if failed:
            log.info(
                "value_recovery.retrying_failed_tickers",
                market=market,
                count=len(failed),
                tickers=failed[:10],  # log up to 10 for debugging
            )
            # Small delay before retry to let yfinance rate-limit window reset
            await asyncio.sleep(2.0)
            retried = await self._batch_fundamentals(failed, market)
            fund_map.update(retried)

            still_failed = [t for t in failed if not fund_map.get(t)]
            if still_failed:
                log.warning(
                    "value_recovery.retry_still_failed",
                    market=market,
                    count=len(still_failed),
                )

        return fund_map

    # ── Batch fundamentals fetch ──────────────────────────────────────────────

    async def _batch_fundamentals(
        self, tickers: list[str], market: str
    ) -> dict[str, dict]:
        """
        Fetch valuation + growth metrics for all candidate tickers in parallel.
        Semaphore-limited to 8 concurrent yfinance calls to avoid HTTP 429s.
        Returns {} for any ticker that fails — handled gracefully in scoring.
        """
        sem = asyncio.Semaphore(8)

        async def _fetch_one(ticker: str) -> tuple[str, dict]:
            import yfinance as yf
            yf_sym = f"{ticker}.NS" if market == "india" else ticker
            async with sem:
                try:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(lambda s=yf_sym: yf.Ticker(s).info),
                        timeout=8.0,
                    )
                    return ticker, {
                        "pe":             _safe_float(info.get("trailingPE")),
                        "forward_pe":     _safe_float(info.get("forwardPE")),
                        "earnings_growth": _safe_float(info.get("earningsGrowth")),
                        "revenue_growth":  _safe_float(info.get("revenueGrowth")),
                        "roe":            _safe_float(info.get("returnOnEquity")),
                        "de_ratio":       _safe_float(info.get("debtToEquity")),
                        "profit_margin":  _safe_float(info.get("profitMargins")),
                        "consensus":      info.get("recommendationKey"),
                        "target":         _safe_float(info.get("targetMeanPrice")),
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
