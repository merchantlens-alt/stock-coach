"""
USETFDataService — US ETF scanner + model portfolio via yfinance.

Why a separate service from the India MF one
────────────────────────────────────────────
US ETF investing is a different game:
  • It's mostly PASSIVE — the edge isn't manager alpha, it's cost + allocation.
  • yfinance gives what mfapi can't: real EXPENSE RATIO and AUM. So cost-aware
    ranking (QQQM 0.15% beats QQQ 0.20% for the same exposure) is real here.
  • The universe is a CURATED set of ~75 major ETFs, not a discovered long tail —
    the good building blocks are well known.

So scoring is cost-led (expense ratio carries real weight), there are no
alpha/decay/closet rule-outs (ETFs are the benchmark), and the model portfolio is
a Boglehead-style lazy allocation rather than five active managers.

Metrics (returns / Sharpe / drawdown / percentile) reuse services.fund_metrics.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from core.config import Settings
from core.logging import get_logger
from models.schemas import FundScanResponse, FundScheme, ModelPortfolioResponse
from services.fund_metrics import (
    compute_metrics,
    percentile_ranks,
    score_fund,
    track_record_tier,
)
from services.fund_portfolio import assemble_portfolio

log = get_logger(__name__)

# ── Curated universe: ticker → category ───────────────────────────────────────
_US_ETF_UNIVERSE: dict[str, str] = {
    # Broad market
    "VTI": "US Broad Market", "VOO": "US Broad Market", "IVV": "US Broad Market",
    "SPY": "US Broad Market", "SPLG": "US Broad Market", "ITOT": "US Broad Market",
    "SCHB": "US Broad Market",
    # Large growth
    "QQQ": "US Large Growth", "QQQM": "US Large Growth", "VUG": "US Large Growth",
    "SCHG": "US Large Growth", "MGK": "US Large Growth", "IWF": "US Large Growth",
    # Large value
    "VTV": "US Large Value", "SCHV": "US Large Value", "IWD": "US Large Value",
    # Dividend
    "SCHD": "US Dividend", "VYM": "US Dividend", "VIG": "US Dividend",
    "DGRO": "US Dividend", "DGRW": "US Dividend", "HDV": "US Dividend", "DVY": "US Dividend",
    # Mid cap
    "VO": "US Mid Cap", "IJH": "US Mid Cap", "MDY": "US Mid Cap", "SCHM": "US Mid Cap",
    # Small cap
    "VB": "US Small Cap", "IJR": "US Small Cap", "IWM": "US Small Cap",
    "VTWO": "US Small Cap", "SCHA": "US Small Cap", "AVUV": "US Small Cap",
    # Technology
    "VGT": "US Technology", "XLK": "US Technology", "SMH": "US Technology",
    "SOXX": "US Technology", "IYW": "US Technology",
    # Sectors
    "XLE": "US Sector", "XLF": "US Sector", "XLV": "US Sector", "XLY": "US Sector",
    "XLP": "US Sector", "XLI": "US Sector", "XLU": "US Sector", "XLB": "US Sector",
    "XLRE": "US Sector", "XLC": "US Sector",
    # International
    "VEA": "International Developed", "IEFA": "International Developed",
    "SCHF": "International Developed", "EFA": "International Developed",
    "VXUS": "International Total", "IXUS": "International Total",
    "VWO": "Emerging Markets", "IEMG": "Emerging Markets", "SCHE": "Emerging Markets",
    # Bonds
    "BND": "Bonds", "AGG": "Bonds", "BNDX": "Bonds", "TLT": "Bonds",
    "VGIT": "Bonds", "IEF": "Bonds",
    # REIT
    "VNQ": "REIT", "SCHH": "REIT", "IYR": "REIT",
}

# ── Model-portfolio slots (Boglehead-style) ───────────────────────────────────
_US_SLOTS = [
    ("Core",          "US Broad Market", [],
     "the foundation — owns the entire US market at rock-bottom cost"),
    ("Growth",        "US Large Growth", ["US Technology"],
     "a growth/tech tilt for higher long-run upside"),
    ("International",  "International Total", ["International Developed"],
     "global diversification beyond the US"),
    ("Income",        "US Dividend", ["US Large Value"],
     "quality dividend payers for stability and yield"),
    ("Diversifier",   "Bonds", ["REIT", "Emerging Markets"],
     "ballast to cushion equity drawdowns"),
]
_US_RISK_WEIGHTS: dict[str, list[float]] = {
    "conservative": [40, 10, 15, 20, 15],
    "balanced":     [45, 20, 20, 10,  5],
    "aggressive":   [45, 30, 20,  5,  0],
}
_US_RISK_RATIONALE: dict[str, str] = {
    "conservative": (
        "A low-cost broad-market core with a real bond sleeve and dividend tilt — "
        "less upside, far shallower drawdowns. Suits shorter horizons."
    ),
    "balanced": (
        "A classic three-fund-plus core: total US market, a growth tilt, and "
        "international, with a light bond sleeve. Low cost, broadly diversified, 7+ year horizon."
    ),
    "aggressive": (
        "Maximally equity, growth-tilted, no bonds — for long horizons (10+ years) "
        "that can ride out volatility. Cost stays minimal so compounding isn't taxed by fees."
    ),
}

_US_SCORE_W = {"long": 0.25, "sharpe": 0.25, "cost": 0.20, "dd": 0.15, "aum": 0.15}
_US_LT_W    = {"long": 0.30, "sharpe": 0.20, "cost": 0.25, "dd": 0.15, "aum": 0.10}
_MIN_HISTORY = 60


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


class _Scanned:
    __slots__ = ("fund", "metrics")

    def __init__(self, fund: FundScheme, metrics: dict) -> None:
        self.fund = fund
        self.metrics = metrics


class USETFDataService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ── Public API ──────────────────────────────────────────────────────────────

    async def scan(self, category: Optional[str] = None) -> FundScanResponse:
        targets = {t: c for t, c in _US_ETF_UNIVERSE.items()
                   if not category or c == category}
        if not targets:
            return FundScanResponse(market="us", funds=[], category=category, scanned_at=datetime.utcnow())

        history = await self._download_history(list(targets))
        infos = await self._fetch_infos(list(targets))

        scanned: list[_Scanned] = []
        for ticker, cat in targets.items():
            navs = history.get(ticker) or []
            if len(navs) < _MIN_HISTORY:
                continue
            m = compute_metrics(navs)
            info = infos.get(ticker, {})
            fund = FundScheme(
                scheme_code=ticker,
                name=info.get("name") or ticker,
                fund_house=info.get("family"),
                category=cat,
                fund_type="etf",
                market="us",
                nav=round(navs[-1], 2),
                expense_ratio=info.get("expense_ratio"),
                aum=info.get("aum"),
                returns_1m=m.get("returns_1m"), returns_3m=m.get("returns_3m"),
                returns_6m=m.get("returns_6m"), returns_1y=m.get("returns_1y"),
                returns_3y_cagr=m.get("returns_3y_cagr"), returns_5y_cagr=m.get("returns_5y_cagr"),
                since_inception_cagr=m.get("since_inception_cagr"),
                volatility=m.get("volatility"), sharpe=m.get("sharpe"),
                max_drawdown=m.get("max_drawdown"),
                track_record=track_record_tier(m.get("history_points", len(navs))),
            )
            scanned.append(_Scanned(fund, m))

        if not scanned:
            return FundScanResponse(market="us", funds=[], category=category, scanned_at=datetime.utcnow())

        self._score(scanned)
        funds = [s.fund for s in scanned]
        funds.sort(key=lambda f: f.fund_score, reverse=True)
        log.info("us_etf.scan_done", category=category or "all", scanned=len(funds))
        return FundScanResponse(
            market="us", funds=funds, category=category,
            universe_size=len(_US_ETF_UNIVERSE), scanned_at=datetime.utcnow(),
        )

    async def build_model_portfolio(self, risk: str = "balanced") -> ModelPortfolioResponse:
        risk = risk if risk in _US_RISK_WEIGHTS else "balanced"
        scan = await self.scan(category=None)
        return assemble_portfolio(
            funds=scan.funds, slots=_US_SLOTS, weights=_US_RISK_WEIGHTS[risk],
            risk=risk, rationale=_US_RISK_RATIONALE[risk], market="us",
            universe_size=scan.universe_size,
        )

    # ── Scoring (category-relative, cost-led) ──────────────────────────────────

    def _score(self, scanned: list[_Scanned]) -> None:
        by_cat: dict[str, list[_Scanned]] = {}
        for s in scanned:
            by_cat.setdefault(s.fund.category or "?", []).append(s)
        for cat, cohort in by_cat.items():
            self._score_cohort(cohort)

    def _score_cohort(self, cohort: list[_Scanned]) -> None:
        if len(cohort) < 4:
            for s in cohort:
                score, signal = score_fund(s.metrics)
                s.fund.fund_score = score
                s.fund.long_term_score = score
                s.fund.entry_signal = signal  # type: ignore[assignment]
                s.fund.entry_reason = self._reason(s.fund)
            self._assign_ranks(cohort)
            return

        def longret(f: FundScheme) -> Optional[float]:
            return f.returns_5y_cagr if f.returns_5y_cagr is not None \
                else f.returns_3y_cagr if f.returns_3y_cagr is not None \
                else f.since_inception_cagr

        p_long   = percentile_ranks([longret(s.fund) for s in cohort], higher_is_better=True)
        p_sharpe = percentile_ranks([s.fund.sharpe for s in cohort], higher_is_better=True)
        p_cost   = percentile_ranks([s.fund.expense_ratio for s in cohort], higher_is_better=False)
        p_dd     = percentile_ranks([s.fund.max_drawdown for s in cohort], higher_is_better=True)
        p_aum    = percentile_ranks([s.fund.aum for s in cohort], higher_is_better=True)

        for i, s in enumerate(cohort):
            w = _US_SCORE_W
            score = round(w["long"] * p_long[i] + w["sharpe"] * p_sharpe[i]
                          + w["cost"] * p_cost[i] + w["dd"] * p_dd[i] + w["aum"] * p_aum[i], 1)
            lw = _US_LT_W
            lt = round(lw["long"] * p_long[i] + lw["sharpe"] * p_sharpe[i]
                       + lw["cost"] * p_cost[i] + lw["dd"] * p_dd[i] + lw["aum"] * p_aum[i], 1)
            s.fund.fund_score = score
            s.fund.long_term_score = lt
            s.fund.entry_signal = (  # type: ignore[assignment]
                "strong_entry" if score >= 65 else "watch" if score >= 42 else "avoid"
            )
            s.fund.entry_reason = self._reason(s.fund)
        self._assign_ranks(cohort)

    @staticmethod
    def _assign_ranks(cohort: list[_Scanned]) -> None:
        ranked = sorted(cohort, key=lambda s: s.fund.fund_score, reverse=True)
        for rank, s in enumerate(ranked, 1):
            s.fund.category_rank = rank
            s.fund.category_size = len(ranked)

    @staticmethod
    def _reason(f: FundScheme) -> str:
        longret = f.returns_5y_cagr or f.returns_3y_cagr or f.since_inception_cagr
        label = "5yr" if f.returns_5y_cagr is not None else "3yr" if f.returns_3y_cagr is not None else "since-incep"
        cost = f"{f.expense_ratio:.2f}% fee" if f.expense_ratio is not None else "low cost"
        rank = f"#{f.category_rank} of {f.category_size} in {f.category}" if f.category_rank else (f.category or "ETF")
        ret = f"{longret:.0f}% {label} CAGR" if longret is not None else "limited history"
        if f.entry_signal == "strong_entry":
            lead = f"Best-in-class {f.category}"
        elif f.entry_signal == "avoid":
            lead = "A pricier or weaker option than its peers"
        else:
            lead = f"A solid {f.category} holding"
        return f"{lead} — {rank} on cost-adjusted long-term return ({cost}, {ret})."

    async def get_price_series(self, ticker: str) -> list[tuple[datetime, float]]:
        """Dated price series [(datetime, close), …] oldest→newest, for backtests."""
        import yfinance as yf

        try:
            df = await asyncio.to_thread(
                lambda: yf.Ticker(ticker).history(period="10y", auto_adjust=True)
            )
        except Exception as exc:
            log.warning("us_etf.series_failed", ticker=ticker, error=str(exc))
            return []
        out: list[tuple[datetime, float]] = []
        try:
            for ts, v in df["Close"].items():
                fv = float(v)
                if fv == fv and fv > 0:
                    dt = ts.to_pydatetime().replace(tzinfo=None)
                    out.append((dt, fv))
        except Exception:
            return []
        return out

    # ── yfinance fetch ──────────────────────────────────────────────────────────

    async def _download_history(self, tickers: list[str]) -> dict[str, list[float]]:
        import pandas as pd
        import yfinance as yf

        try:
            df: pd.DataFrame = await asyncio.to_thread(
                yf.download, " ".join(tickers), period="10y",
                auto_adjust=True, progress=False,
            )
        except Exception as exc:
            log.warning("us_etf.history_download_failed", error=str(exc))
            return {}

        out: dict[str, list[float]] = {}
        if df.empty:
            return out
        for t in tickers:
            try:
                series = df["Close"][t].dropna() if len(tickers) > 1 else df["Close"].dropna()
                navs = [float(v) for v in series.values if v == v and v > 0]
                if navs:
                    out[t] = navs
            except Exception:
                continue
        return out

    async def _fetch_infos(self, tickers: list[str]) -> dict[str, dict]:
        sem = asyncio.Semaphore(10)

        async def one(ticker: str) -> tuple[str, dict]:
            import yfinance as yf
            async with sem:
                try:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(lambda: yf.Ticker(ticker).info), timeout=12.0
                    )
                except Exception:
                    return ticker, {}
            er = _safe_float(info.get("netExpenseRatio"))
            if er is None:
                er = _safe_float(info.get("annualReportExpenseRatio"))
            return ticker, {
                "name": info.get("longName") or info.get("shortName"),
                "family": info.get("fundFamily"),
                "expense_ratio": er,
                "aum": _safe_float(info.get("totalAssets")),
            }

        results = await asyncio.gather(*[one(t) for t in tickers], return_exceptions=True)
        return {
            t: d for r in results if not isinstance(r, Exception) for t, d in [r]
        }
