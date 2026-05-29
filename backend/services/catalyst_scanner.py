"""
CatalystScannerService — finds stocks with unusual volume + a confirmed news
catalyst and ranks them by a composite momentum score (0-100).

Pipeline (cold path, ~12-18 s):
  1. Screener  — top movers from yfinance/Yahoo Finance screener (~1 s)
  2. Avg volume — 20-day volume history via yf.download, one batch call (~6-8 s)
  3. News       — yfinance headlines for each ticker in parallel (~2 s)
  4. Score      — volume ratio + change % + catalyst flag → momentum score
  5. AI verdict — one Gemini batch call for top 10 stocks (~3-5 s)

Result is cached 30 min — the scan is designed to show what's moving RIGHT NOW,
so a shorter TTL than the 2-hour gainer cache is appropriate.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal, Optional

import yfinance as yf

from agents.catalyst_analyst import CatalystAnalystAgent
from core.config import Settings
from core.logging import get_logger
from models.schemas import (
    CatalystPlay,
    CatalystScanResponse,
    CatalystType,
    Market,
    NewsItem,
)
from services.market_data import MarketDataService, _has_catalyst_in_headlines
from services.news_fetcher import NewsFetcher

log = get_logger(__name__)

# ── Catalyst type keyword map (ordered — first match wins) ────────────────────
_TYPE_KEYWORDS: list[tuple[CatalystType, list[str]]] = [
    ("fda_approval",    ["fda", "approval", "approved", "clearance", "cleared", "clinical trial", "nda", "bla"]),
    ("acquisition",     ["acquisition", "acquires", "merger", "buyout", "takeover", "acquire"]),
    ("earnings",        ["earnings", "revenue beat", "eps beat", "quarterly result", "profit surge", "record revenue", "guidance raised"]),
    ("partnership",     ["partnership", "collaboration", "joint venture", "licensing deal", "strategic deal"]),
    ("regulatory",      ["contract", "nasa", "dod", "pentagon", "darpa", "government award", "grant award", "federal contract", "sebi", "index inclusion"]),
    ("analyst_upgrade", ["analyst", "upgrade", "overweight", "buy rating", "price target raised"]),
    ("macro",           ["fed", "inflation", "interest rate", "macro", "gdp", "cpi"]),
]


def _classify_catalyst_type(headlines: list[str]) -> CatalystType:
    combined = " ".join(h.lower() for h in headlines)
    for cat_type, keywords in _TYPE_KEYWORDS:
        if any(kw in combined for kw in keywords):
            return cat_type
    return "unknown"


def _extract_catalyst_headline(headlines: list[str]) -> Optional[str]:
    """Return the first headline that contains a catalyst keyword, or None."""
    if not headlines:
        return None
    # Return the headline that matches catalyst keywords, else first headline
    combined_check = " ".join(h.lower() for h in headlines)
    for _, keywords in _TYPE_KEYWORDS:
        for kw in keywords:
            if kw in combined_check:
                for h in headlines:
                    if kw in h.lower():
                        return h[:120]
    return headlines[0][:120] if headlines else None


def _compute_momentum_score(
    change_pct: float,
    volume_ratio: Optional[float],
    has_catalyst: bool,
) -> float:
    """
    Composite score 0-100:
      Volume ratio component  — 0-40 pts  (how unusual is today's volume)
      Change % component      — 0-40 pts  (magnitude of the price move)
      Catalyst bonus          — 0-20 pts  (confirmed news event)
    """
    score = 0.0

    # Volume ratio — most important signal: unusual volume = institutional conviction
    if volume_ratio is None:
        score += 10  # unknown, partial credit
    elif volume_ratio >= 5:
        score += 40
    elif volume_ratio >= 3:
        score += 32
    elif volume_ratio >= 2:
        score += 22
    elif volume_ratio >= 1.5:
        score += 12
    else:
        score += 4

    # Change % — size of the move matters, but huge % on tiny stocks is suspect
    if change_pct >= 25:
        score += 40
    elif change_pct >= 15:
        score += 33
    elif change_pct >= 8:
        score += 25
    elif change_pct >= 3:
        score += 14
    else:
        score += 4

    # Catalyst bonus
    if has_catalyst:
        score += 20

    return round(min(100.0, score), 1)


def _score_to_signal(score: float) -> Literal["strong_move", "emerging", "noise"]:
    if score >= 60:
        return "strong_move"
    if score >= 30:
        return "emerging"
    return "noise"


class CatalystScannerService:
    def __init__(
        self,
        settings: Settings,
        market_data: MarketDataService,
        news_fetcher: NewsFetcher,
        analyst: CatalystAnalystAgent,
    ) -> None:
        self._settings = settings
        self._market_data = market_data
        self._news_fetcher = news_fetcher
        self._analyst = analyst

    async def scan(self, market: Market, limit: int = 15) -> CatalystScanResponse:
        """
        Full catalyst scan pipeline. Returns a CatalystScanResponse with up to
        `limit` plays ranked by momentum score.
        """
        # ── 1. Get raw movers from screener ───────────────────────────────────
        raw_movers = await self._market_data.get_raw_movers(market)
        if not raw_movers:
            log.warning("catalyst_scanner.no_movers", market=market)
            return CatalystScanResponse(market=market, plays=[])

        # Work with top 20 by change_pct — screener already sorts desc
        raw_movers = raw_movers[:20]
        tickers = [r["ticker"] for r in raw_movers]

        log.info("catalyst_scanner.scan_start", market=market, movers=len(raw_movers))

        # ── 2. Fetch avg volumes + news in parallel ───────────────────────────
        avg_volumes, news_map = await asyncio.gather(
            self._fetch_avg_volumes(tickers, market),
            self._fetch_batch_headlines(tickers, market),
        )

        # ── 3. Score each mover ───────────────────────────────────────────────
        enriched: list[dict[str, Any]] = []
        for r in raw_movers:
            ticker = r["ticker"]
            current_vol = r["volume"]
            avg_vol = avg_volumes.get(ticker)
            vol_ratio = (
                round(current_vol / avg_vol, 1)
                if avg_vol and avg_vol > 0
                else None
            )

            headlines = news_map.get(ticker, [])
            has_catalyst = _has_catalyst_in_headlines(headlines)
            catalyst_type = _classify_catalyst_type(headlines)
            headline_catalyst = _extract_catalyst_headline(headlines) if has_catalyst else None

            score = _compute_momentum_score(r["change_pct"], vol_ratio, has_catalyst)
            signal = _score_to_signal(score)

            enriched.append({
                "ticker": ticker,
                "name": r.get("name", ticker),
                "sector": r.get("sector"),
                "price": r["price"],
                "change_pct": r["change_pct"],
                "change_abs": r.get("change_abs", 0.0),
                "volume": current_vol,
                "avg_volume": int(avg_vol) if avg_vol else None,
                "volume_ratio": vol_ratio,
                "momentum_score": score,
                "catalyst_type": catalyst_type,
                "signal": signal,
                "headline_catalyst": headline_catalyst,
                "has_catalyst": has_catalyst,
            })

        # Sort by momentum score descending, take top limit
        enriched.sort(key=lambda x: x["momentum_score"], reverse=True)
        top = enriched[:limit]

        # ── 4. AI verdicts for top 10 ─────────────────────────────────────────
        verdicts = await self._analyst.analyse(top[:10], market)

        # ── 5. Build response ─────────────────────────────────────────────────
        plays: list[CatalystPlay] = []
        for e in top:
            ticker = e["ticker"]
            plays.append(
                CatalystPlay(
                    ticker=ticker,
                    name=e["name"],
                    market=market,
                    sector=e.get("sector"),
                    price=e["price"],
                    change_pct=e["change_pct"],
                    change_abs=e["change_abs"],
                    volume=e["volume"],
                    avg_volume=e["avg_volume"],
                    volume_ratio=e["volume_ratio"],
                    momentum_score=e["momentum_score"],
                    catalyst_type=e["catalyst_type"],
                    signal=e["signal"],
                    headline_catalyst=e.get("headline_catalyst"),
                    ai_verdict=verdicts.get(ticker, ""),
                )
            )

        log.info(
            "catalyst_scanner.scan_done",
            market=market,
            plays=len(plays),
            strong=sum(1 for p in plays if p.signal == "strong_move"),
            emerging=sum(1 for p in plays if p.signal == "emerging"),
        )
        return CatalystScanResponse(market=market, plays=plays, from_cache=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_avg_volumes(
        self, tickers: list[str], market: str
    ) -> dict[str, Optional[float]]:
        """
        Batch download 20 days of volume history via yf.download (one call),
        compute the 19-day average (excludes today), return dict of ticker → avg.
        Falls back to {} on any error — the scanner handles missing avg gracefully.
        """
        yf_syms = [f"{t}.NS" if market == "india" else t for t in tickers]
        tickers_str = " ".join(yf_syms)
        sym_to_ticker = dict(zip(yf_syms, tickers))

        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    yf.download,
                    tickers_str,
                    period="20d",
                    auto_adjust=True,
                    progress=False,
                ),
                timeout=15.0,
            )
        except Exception as exc:
            log.warning("catalyst_scanner.avg_vol_download_failed", error=str(exc))
            return {t: None for t in tickers}

        result: dict[str, Optional[float]] = {}
        single_ticker = len(tickers) == 1

        for sym, ticker in sym_to_ticker.items():
            try:
                if single_ticker:
                    vol_series = df["Volume"].dropna()
                else:
                    vol_series = df["Volume"][sym].dropna()

                if len(vol_series) > 1:
                    # Exclude today (last row) from the avg
                    avg = float(vol_series.iloc[:-1].mean())
                elif len(vol_series) == 1:
                    avg = float(vol_series.iloc[0])
                else:
                    avg = None
                result[ticker] = avg
            except Exception:
                result[ticker] = None

        return result

    async def _fetch_batch_headlines(
        self, tickers: list[str], market: str
    ) -> dict[str, list[str]]:
        """
        Fetch up to 5 recent headlines for each ticker from yfinance in parallel.
        Returns dict of ticker → list of headline strings.
        """
        async def _fetch_one(ticker: str) -> tuple[str, list[str]]:
            yf_sym = f"{ticker}.NS" if market == "india" else ticker
            try:
                news = await asyncio.wait_for(
                    asyncio.to_thread(lambda: yf.Ticker(yf_sym).news),
                    timeout=6.0,
                )
                titles: list[str] = []
                for item in (news or [])[:5]:
                    title = (
                        item.get("content", {}).get("title")
                        or item.get("title", "")
                    )
                    if title:
                        titles.append(title)
                return ticker, titles
            except Exception:
                return ticker, []

        results = await asyncio.gather(*[_fetch_one(t) for t in tickers])
        return dict(results)
