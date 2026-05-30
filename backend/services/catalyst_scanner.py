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

# ── Ticker universes for accumulation-phase scan ──────────────────────────────
# Liquid stocks where unusual-volume-but-flat-price is meaningful.
# Kept small (~50 US, ~30 India) so yf.download finishes in ~5-8 s.

_US_TICKER_UNIVERSE: list[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "AMD",
    # Semis
    "AVGO", "QCOM", "MU", "INTC", "AMAT", "KLAC", "LRCX", "ON",
    # Biotech / Pharma — high catalyst potential
    "MRNA", "BNTX", "GILD", "BIIB", "REGN", "VRTX", "ABBV", "LLY", "PFE", "BMY",
    # Healthcare devices
    "ISRG", "DXCM",
    # Energy / clean
    "FSLR", "ENPH", "NEE", "CVX", "XOM",
    # Finance
    "GS", "MS", "JPM", "BAC",
    # Industrial / Aerospace — catalyst-prone
    "BA", "LMT", "RTX", "GE", "NOC",
    # Mid / small caps with catalyst potential
    "SMCI", "PLTR", "IONQ", "RKLB", "SOUN", "MSTR", "SOFI", "HOOD",
]

_INDIA_TICKER_UNIVERSE: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "BAJFINANCE", "KOTAKBANK", "AXISBANK", "LT",
    "HCLTECH", "WIPRO", "ASIANPAINT", "MARUTI", "TATAMOTORS", "ULTRACEMCO",
    "ADANIENT", "ADANIPORTS", "SUNPHARMA", "DIVISLAB", "CIPLA", "DRREDDY",
    "NESTLEIND", "TITAN", "BAJAJFINSV", "PERSISTENT", "MPHASIS",
    "COFORGE", "ZOMATO", "PAYTM",
]

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


def _compute_potential_score(vol_ratio: float) -> float:
    """
    Score for accumulation-phase stocks (flat price, high volume).
    Purely volume-anomaly driven — 0-100 scale mirroring momentum score tiers.
    """
    if vol_ratio >= 5:
        return 85.0
    if vol_ratio >= 4:
        return 70.0
    if vol_ratio >= 3:
        return 55.0
    if vol_ratio >= 2.5:
        return 42.0
    return 30.0


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
        Full catalyst scan pipeline. Returns a CatalystScanResponse with:
          - up to `limit` movers ranked by momentum score
          - up to 5 accumulation-phase plays (high volume, flat price) appended after
        """
        # ── 1. Screener + universe scan in parallel ───────────────────────────
        raw_movers, potential_candidates = await asyncio.gather(
            self._market_data.get_raw_movers(market),
            self._scan_potential_universe(market),
        )

        raw_movers = raw_movers[:20]
        mover_tickers = {r["ticker"] for r in raw_movers}

        # Dedup: drop universe candidates already caught by the screener
        potential_candidates = [
            p for p in potential_candidates if p["ticker"] not in mover_tickers
        ]
        potential_candidates.sort(key=lambda x: x.get("volume_ratio", 0), reverse=True)
        potential_candidates = potential_candidates[:10]  # cap universe candidates

        if not raw_movers and not potential_candidates:
            log.warning("catalyst_scanner.no_plays", market=market)
            return CatalystScanResponse(market=market, plays=[])

        all_tickers = [r["ticker"] for r in raw_movers] + [
            p["ticker"] for p in potential_candidates
        ]
        log.info(
            "catalyst_scanner.scan_start",
            market=market,
            movers=len(raw_movers),
            potential=len(potential_candidates),
        )

        # ── 2. Fetch avg volumes (screener movers) + headlines (all) ─────────
        if raw_movers:
            avg_volumes, news_map = await asyncio.gather(
                self._fetch_avg_volumes([r["ticker"] for r in raw_movers], market),
                self._fetch_batch_headlines(all_tickers, market),
            )
        else:
            avg_volumes = {}
            news_map = (
                await self._fetch_batch_headlines(all_tickers, market)
                if all_tickers else {}
            )

        # ── 3. Score screener movers ──────────────────────────────────────────
        enriched_movers: list[dict[str, Any]] = []
        for r in raw_movers:
            ticker = r["ticker"]
            current_vol = r["volume"]
            avg_vol = avg_volumes.get(ticker)
            vol_ratio = (
                round(current_vol / avg_vol, 1) if avg_vol and avg_vol > 0 else None
            )

            headlines = news_map.get(ticker, [])
            has_catalyst = _has_catalyst_in_headlines(headlines)
            catalyst_type = _classify_catalyst_type(headlines)
            headline_catalyst = _extract_catalyst_headline(headlines) if has_catalyst else None

            score = _compute_momentum_score(r["change_pct"], vol_ratio, has_catalyst)
            signal = _score_to_signal(score)

            enriched_movers.append({
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

        # ── 4. Enrich potential (accumulation-phase) candidates ───────────────
        enriched_potential: list[dict[str, Any]] = []
        for p in potential_candidates:
            ticker = p["ticker"]
            headlines = news_map.get(ticker, [])
            has_catalyst = _has_catalyst_in_headlines(headlines)
            catalyst_type = _classify_catalyst_type(headlines)
            headline_catalyst = _extract_catalyst_headline(headlines) if has_catalyst else None
            score = _compute_potential_score(p.get("volume_ratio") or 2.0)

            enriched_potential.append({
                **p,
                "signal": "potential",
                "momentum_score": score,
                "catalyst_type": catalyst_type,
                "headline_catalyst": headline_catalyst,
                "has_catalyst": has_catalyst,
            })

        # ── 5. Sort movers by score; keep potential ordered by vol_ratio ──────
        enriched_movers.sort(key=lambda x: x["momentum_score"], reverse=True)
        top_movers = enriched_movers[:limit]

        # ── 6. AI verdicts: top 7 movers + top 3 potential ───────────────────
        verdict_batch = top_movers[:7] + enriched_potential[:3]
        verdicts = await self._analyst.analyse(verdict_batch, market)

        # ── 7. Build response — movers first, then potential ──────────────────
        plays: list[CatalystPlay] = []
        for e in top_movers:
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

        for e in enriched_potential:
            ticker = e["ticker"]
            plays.append(
                CatalystPlay(
                    ticker=ticker,
                    name=e.get("name", ticker),
                    market=market,
                    sector=e.get("sector"),
                    price=e["price"],
                    change_pct=e["change_pct"],
                    change_abs=e["change_abs"],
                    volume=e["volume"],
                    avg_volume=e.get("avg_volume"),
                    volume_ratio=e.get("volume_ratio"),
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
            potential=sum(1 for p in plays if p.signal == "potential"),
        )
        return CatalystScanResponse(market=market, plays=plays, from_cache=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _scan_potential_universe(self, market: Market) -> list[dict[str, Any]]:
        """
        Scan a fixed universe of liquid stocks for the accumulation pattern:
          volume_ratio >= 2.0  AND  -2% <= change_pct < 5%

        These stocks haven't moved yet but smart money is building a position —
        the classic setup seen before a catalyst announcement (e.g. ASTC before
        its 147% NASA-contract move).

        Uses a single yf.download (5-day daily OHLCV) so it's one API call.
        Returns a list of raw dicts with the same shape as screener movers.
        """
        universe = _US_TICKER_UNIVERSE if market == "us" else _INDIA_TICKER_UNIVERSE
        yf_syms = [f"{t}.NS" if market == "india" else t for t in universe]
        sym_to_ticker = dict(zip(yf_syms, universe))

        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    yf.download,
                    " ".join(yf_syms),
                    period="5d",
                    auto_adjust=True,
                    progress=False,
                ),
                timeout=20.0,
            )
        except Exception as exc:
            log.warning("catalyst_scanner.potential_scan_failed", error=str(exc))
            return []

        if df is None or df.empty:
            return []

        candidates: list[dict[str, Any]] = []
        single = len(universe) == 1

        for sym, ticker in sym_to_ticker.items():
            try:
                if single:
                    close_series = df["Close"].dropna()
                    vol_series = df["Volume"].dropna()
                else:
                    close_series = df["Close"][sym].dropna()
                    vol_series = df["Volume"][sym].dropna()

                if len(close_series) < 2 or len(vol_series) < 2:
                    continue

                today_price = float(close_series.iloc[-1])
                prev_close = float(close_series.iloc[-2])
                if prev_close <= 0:
                    continue

                change_pct = round((today_price - prev_close) / prev_close * 100, 2)
                today_vol = float(vol_series.iloc[-1])
                # avg over last 4 complete days (exclude today)
                hist_vols = vol_series.iloc[:-1]
                avg_vol = float(hist_vols.mean()) if len(hist_vols) > 0 else 0.0

                if avg_vol <= 0 or today_vol <= 0:
                    continue

                vol_ratio = round(today_vol / avg_vol, 1)

                # Accumulation pattern: high volume AND flat price
                if vol_ratio >= 2.0 and -2.0 <= change_pct < 5.0:
                    candidates.append({
                        "ticker": ticker,
                        "name": ticker,  # enriched by analysis panel on drill-down
                        "sector": None,
                        "price": round(today_price, 4),
                        "change_pct": change_pct,
                        "change_abs": round(today_price - prev_close, 4),
                        "volume": int(today_vol),
                        "avg_volume": int(avg_vol),
                        "volume_ratio": vol_ratio,
                    })
            except Exception:
                continue

        log.info(
            "catalyst_scanner.potential_candidates",
            market=market,
            universe_size=len(universe),
            candidates=len(candidates),
        )
        return candidates

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
