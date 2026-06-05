from __future__ import annotations

"""
FundamentalEnricher — deep valuation, growth CAGR, and peer metrics.

Runs in parallel with the AI analysis call so it never adds to total
request latency.  All yfinance calls are wrapped in asyncio.to_thread
and protected by individual try/except so a single bad metric never
blocks the rest.  If yfinance is unavailable the method returns a
partially-populated FundamentalsData — never raises.
"""

import asyncio
from datetime import date
from typing import Optional

import yfinance as yf

from core.logging import get_logger
from models.schemas import (
    FundamentalsData,
    PeerComparison,
    ValuationBand,
    ValuationClassification,
)

log = get_logger(__name__)


# ── Peer map ──────────────────────────────────────────────────────────────────
# Maps yfinance symbol → up to 3 close peers (same sector/business model).
# India tickers end in .NS; US tickers are bare.
_PEER_MAP: dict[str, list[str]] = {
    # India — IT Services
    "TCS.NS":        ["INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "INFY.NS":       ["TCS.NS", "WIPRO.NS", "HCLTECH.NS"],
    "WIPRO.NS":      ["TCS.NS", "INFY.NS", "HCLTECH.NS"],
    "HCLTECH.NS":    ["TCS.NS", "INFY.NS", "WIPRO.NS"],
    "TECHM.NS":      ["TCS.NS", "INFY.NS", "WIPRO.NS"],
    "LTIM.NS":       ["TCS.NS", "INFY.NS", "MPHASIS.NS"],
    "MPHASIS.NS":    ["LTIM.NS", "INFY.NS", "COFORGE.NS"],
    "COFORGE.NS":    ["MPHASIS.NS", "LTIM.NS", "PERSISTENT.NS"],
    "PERSISTENT.NS": ["COFORGE.NS", "MPHASIS.NS", "LTIM.NS"],
    # India — Banking
    "HDFCBANK.NS":   ["ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
    "ICICIBANK.NS":  ["HDFCBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
    "KOTAKBANK.NS":  ["HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS"],
    "AXISBANK.NS":   ["HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS"],
    "SBIN.NS":       ["HDFCBANK.NS", "ICICIBANK.NS", "BANKBARODA.NS"],
    "INDUSINDBK.NS": ["AXISBANK.NS", "KOTAKBANK.NS", "FEDERALBNK.NS"],
    # India — FMCG
    "HINDUNILVR.NS": ["NESTLEIND.NS", "DABUR.NS", "MARICO.NS"],
    "NESTLEIND.NS":  ["HINDUNILVR.NS", "DABUR.NS", "BRITANNIA.NS"],
    "DABUR.NS":      ["HINDUNILVR.NS", "MARICO.NS", "COLPAL.NS"],
    "MARICO.NS":     ["DABUR.NS", "HINDUNILVR.NS", "COLPAL.NS"],
    "BRITANNIA.NS":  ["NESTLEIND.NS", "HINDUNILVR.NS", "TATACONSUM.NS"],
    # India — Auto
    "MARUTI.NS":     ["M&M.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS"],
    "TATAMOTORS.NS": ["MARUTI.NS", "M&M.NS", "EICHERMOT.NS"],
    "M&M.NS":        ["MARUTI.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS"],
    "BAJAJ-AUTO.NS": ["HEROMOTOCO.NS", "TVSMOTORS.NS", "EICHERMOT.NS"],
    "HEROMOTOCO.NS": ["BAJAJ-AUTO.NS", "TVSMOTORS.NS", "EICHERMOT.NS"],
    "EICHERMOT.NS":  ["BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "TVSMOTORS.NS"],
    # India — Pharma
    "SUNPHARMA.NS":  ["DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS"],
    "DRREDDY.NS":    ["SUNPHARMA.NS", "CIPLA.NS", "AUROPHARMA.NS"],
    "CIPLA.NS":      ["SUNPHARMA.NS", "DRREDDY.NS", "LUPIN.NS"],
    "DIVISLAB.NS":   ["SUNPHARMA.NS", "DRREDDY.NS", "APLLTD.NS"],
    # India — Energy
    "RELIANCE.NS":   ["ONGC.NS", "IOC.NS", "BPCL.NS"],
    "ONGC.NS":       ["RELIANCE.NS", "OIL.NS", "BPCL.NS"],
    # India — Cement
    "ULTRACEMCO.NS": ["SHREECEM.NS", "AMBUJACEM.NS", "ACC.NS"],
    "SHREECEM.NS":   ["ULTRACEMCO.NS", "AMBUJACEM.NS", "ACC.NS"],
    # India — Steel / Metals
    "TATASTEEL.NS":  ["JSWSTEEL.NS", "SAIL.NS", "HINDALCO.NS"],
    "JSWSTEEL.NS":   ["TATASTEEL.NS", "SAIL.NS", "NMDC.NS"],
    # India — NBFC / Capital Markets
    "BAJFINANCE.NS": ["BAJAJFINSV.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS"],
    # India — Power
    "POWERGRID.NS":  ["NTPC.NS", "TATAPOWER.NS", "ADANIPOWER.NS"],
    "NTPC.NS":       ["POWERGRID.NS", "TATAPOWER.NS", "NHPC.NS"],
    # India — Insurance
    "HDFCLIFE.NS":   ["SBILIFE.NS", "ICICIGI.NS", "ICICIPRULI.NS"],
    "SBILIFE.NS":    ["HDFCLIFE.NS", "ICICIGI.NS", "MAXFINSERV.NS"],
    # US — Big Tech
    "AAPL":  ["MSFT", "GOOGL", "META"],
    "MSFT":  ["AAPL", "GOOGL", "AMZN"],
    "GOOGL": ["MSFT", "META", "AMZN"],
    "META":  ["GOOGL", "SNAP", "PINS"],
    "AMZN":  ["MSFT", "GOOGL", "SHOP"],
    # US — Semiconductors
    "NVDA":  ["AMD", "INTC", "QCOM"],
    "AMD":   ["NVDA", "INTC", "QCOM"],
    "INTC":  ["AMD", "NVDA", "QCOM"],
    "QCOM":  ["NVDA", "AMD", "AVGO"],
    "AVGO":  ["QCOM", "NVDA", "AMD"],
    # US — Financials
    "JPM":   ["BAC", "WFC", "GS"],
    "BAC":   ["JPM", "WFC", "C"],
    "GS":    ["JPM", "MS", "C"],
    "MS":    ["GS", "JPM", "BLK"],
    # US — Healthcare
    "JNJ":   ["PFE", "MRK", "ABT"],
    "PFE":   ["JNJ", "MRK", "BMY"],
    "UNH":   ["CVS", "CI", "HUM"],
    # US — Consumer / Retail
    "WMT":   ["TGT", "COST", "AMZN"],
    "TGT":   ["WMT", "COST", "KR"],
    # US — Energy
    "XOM":   ["CVX", "COP", "SLB"],
    "CVX":   ["XOM", "COP", "EOG"],
    # US — EV / Auto
    "TSLA":  ["GM", "F", "RIVN"],
}


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _safe_float(val: object) -> Optional[float]:
    """Convert to float, returning None for None / NaN / invalid types."""
    try:
        f = float(val)  # type: ignore[arg-type]
        return None if f != f else f          # NaN check: NaN != NaN is True
    except (TypeError, ValueError):
        return None


def compute_cagr(start: float, end: float, years: int) -> Optional[float]:
    """
    Compound Annual Growth Rate = (end/start)^(1/years) - 1.
    Returns decimal (0.15 = 15%).  None when inputs are invalid.
    """
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def compute_valuation_signal(
    current: Optional[float],
    sector_avg: Optional[float],
    hist_avg: Optional[float],
) -> Optional[ValuationBand]:
    """
    Compare current metric against sector peer average and own 5-year average.

    CHEAP  — current trades below BOTH benchmarks by >10%
    EXPENSIVE — current trades above BOTH benchmarks by >10%
    FAIR   — within 10% of at least one benchmark (or only one benchmark available)
    None   — insufficient data to make a call
    """
    if current is None:
        return None

    votes: list[str] = []

    for benchmark in (sector_avg, hist_avg):
        if benchmark is None or benchmark <= 0:
            continue
        ratio = current / benchmark
        if ratio < 0.90:
            votes.append("cheap")
        elif ratio > 1.10:
            votes.append("expensive")
        else:
            votes.append("fair")

    if not votes:
        return None
    if all(v == "cheap" for v in votes):
        return "cheap"
    if all(v == "expensive" for v in votes):
        return "expensive"
    return "fair"


def compute_overall_valuation(
    signals: list[Optional[ValuationBand]],
) -> Optional[ValuationClassification]:
    """
    Roll up per-metric signals into one overall classification.

    ≥2 cheap    → undervalued
    ≥2 expensive → overvalued
    mix of cheap + expensive → mixed
    all fair (or only 1 signal) → fairly_valued
    all None → None
    """
    valid = [s for s in signals if s is not None]
    if not valid:
        return None
    cheap = sum(1 for s in valid if s == "cheap")
    expensive = sum(1 for s in valid if s == "expensive")
    if cheap >= 2:
        return "undervalued"
    if expensive >= 2:
        return "overvalued"
    if cheap >= 1 and expensive >= 1:
        return "mixed"
    return "fairly_valued"


# ── Service ───────────────────────────────────────────────────────────────────

class FundamentalEnricher:
    """
    Enriches FundamentalsData with deep metrics fetched from yfinance.

    All blocking yfinance calls run in asyncio.to_thread.
    The whole enrichment is designed to be cancellation-safe: awaiting
    the coroutine with asyncio.wait_for(timeout=12) is safe.
    """

    async def enrich(
        self,
        ticker: str,
        market: str,
        existing: Optional[FundamentalsData] = None,
    ) -> FundamentalsData:
        """
        Fetch deep fundamentals and return an enriched FundamentalsData.
        Merges with `existing` (the basic data already fetched by the detail
        endpoint) so no data is lost.  Never raises.
        """
        yf_sym = f"{ticker}.NS" if market == "india" else ticker
        peer_syms = _PEER_MAP.get(yf_sym, [])[:3]

        log.info("fundamental_enricher.start", ticker=yf_sym, peers=peer_syms)

        # Parallel: main ticker data + each peer (independent yfinance calls)
        tasks = [asyncio.to_thread(self._fetch_main, yf_sym)] + [
            asyncio.to_thread(self._fetch_peer, p) for p in peer_syms
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        main_data: dict = results[0] if not isinstance(results[0], Exception) else {}
        if isinstance(results[0], Exception):
            log.warning(
                "fundamental_enricher.main_failed",
                ticker=yf_sym,
                error=str(results[0]),
            )

        peer_rows: list[dict] = [
            r for r in results[1:] if isinstance(r, dict) and r
        ]

        return self._build(existing, main_data, peer_rows)

    # ── Blocking fetchers (run in thread) ─────────────────────────────────────

    def _fetch_main(self, yf_sym: str) -> dict:
        t = yf.Ticker(yf_sym)
        info = {}
        fin = bal = cf = hist = None
        try:
            info = t.info or {}
        except Exception as exc:
            log.warning("fundamental_enricher.info_failed", sym=yf_sym, error=str(exc))
        try:
            fin = t.financials
        except Exception:
            pass
        try:
            bal = t.balance_sheet
        except Exception:
            pass
        try:
            cf = t.cashflow
        except Exception:
            pass
        try:
            hist = t.history(period="5y", interval="1mo")
        except Exception:
            pass
        return {"info": info, "financials": fin, "balance_sheet": bal,
                "cashflow": cf, "price_history": hist}

    def _fetch_peer(self, peer_sym: str) -> dict:
        try:
            info = yf.Ticker(peer_sym).info or {}
        except Exception:
            return {}
        short = peer_sym.replace(".NS", "").replace(".BO", "")
        de = self._de_from_info(info)
        return {
            "ticker": short,
            "name": info.get("longName") or info.get("shortName") or short,
            "pe":  _safe_float(info.get("trailingPE")),
            "pb":  _safe_float(info.get("priceToBook")),
            "roe": _safe_float(info.get("returnOnEquity")),
            "revenue_growth": _safe_float(info.get("revenueGrowth")),
            "de_ratio": de,
        }

    # ── Internal computation helpers ──────────────────────────────────────────

    @staticmethod
    def _de_from_info(info: dict) -> Optional[float]:
        debt = _safe_float(info.get("totalDebt"))
        eq = _safe_float(info.get("totalStockholderEquity")) or \
             _safe_float(info.get("stockholdersEquity"))
        if debt is not None and eq and eq > 0:
            return round(debt / eq, 2)
        return None

    @staticmethod
    def _annual_series(df: object, *names: str) -> list[float]:
        """
        Extract an annual metric from a yfinance financial DataFrame.
        Returns list of floats, most recent first, NaN excluded.
        """
        if df is None:
            return []
        try:
            import pandas as pd
            for name in names:
                if name in df.index:  # type: ignore[operator]
                    series = df.loc[name]  # type: ignore[index]
                    # Sort descending so most recent is index 0
                    series = series.sort_index(ascending=False).dropna()
                    vals = [float(v) for v in series.values if v == v]  # drop NaN
                    if vals:
                        return vals
        except Exception:
            pass
        return []

    def _cagr_from_series(self, series: list[float], years: int) -> Optional[float]:
        """Given most-recent-first annual series, compute CAGR over `years` years."""
        # Clamp to available data
        if len(series) < 2:
            return None
        actual_years = min(years, len(series) - 1)
        if actual_years <= 0:
            return None
        return compute_cagr(series[actual_years], series[0], actual_years)

    def _roe_history(self, fin: object, bal: object) -> list[float]:
        """ROE = Net Income / Stockholders Equity for each annual period."""
        ni = self._annual_series(fin, "Net Income")
        eq = self._annual_series(
            bal, "Stockholders Equity", "Common Stock Equity",
            "Total Stockholder Equity",
        )
        if not ni or not eq:
            return []
        result = []
        for i, net_income in enumerate(ni):
            if i < len(eq) and eq[i] > 0:
                result.append(net_income / eq[i])
        return result

    def _roce(self, info: dict, fin: object, bal: object) -> Optional[float]:
        """ROCE = EBIT / Capital Employed (Total Assets - Current Liabilities)."""
        ebit_series = self._annual_series(fin, "EBIT", "Operating Income")
        if not ebit_series:
            return None
        ebit = ebit_series[0]
        total_assets = _safe_float(info.get("totalAssets"))
        curr_liab = _safe_float(info.get("totalCurrentLiabilities"))
        if total_assets and curr_liab:
            cap_emp = total_assets - curr_liab
            if cap_emp > 0:
                return ebit / cap_emp
        return None

    def _historical_pe(self, info: dict, fin: object, hist: object) -> list[float]:
        """
        Approximate annual historical P/E for the past 5 years.
        Uses year-end close price and annual EPS from financials.
        """
        try:
            import pandas as pd

            eps_series = self._annual_series(fin, "Basic EPS", "Diluted EPS")
            if not eps_series:
                # Fall back: Net Income / shares outstanding
                ni_series = self._annual_series(fin, "Net Income")
                shares = _safe_float(info.get("sharesOutstanding"))
                if ni_series and shares and shares > 0:
                    eps_series = [ni / shares for ni in ni_series]

            if not eps_series or hist is None or (hasattr(hist, "empty") and hist.empty):
                return []

            ph = hist.copy()
            ph.index = pd.to_datetime(ph.index)
            if ph.index.tz is not None:
                ph.index = ph.index.tz_localize(None)

            pe_list: list[float] = []
            current_year = date.today().year
            for i, eps in enumerate(eps_series[:5]):
                if not eps or eps <= 0:
                    continue
                yr = current_year - i
                yr_slice = ph[ph.index.year == yr]
                if yr_slice.empty:
                    continue
                close = float(yr_slice["Close"].iloc[-1])
                if close > 0:
                    pe_list.append(close / eps)
            return pe_list
        except Exception as exc:
            log.warning("fundamental_enricher.pe_history_failed", error=str(exc))
            return []

    def _interest_coverage(self, fin: object) -> Optional[float]:
        """Interest Coverage = EBIT / |Interest Expense|."""
        ebit = self._annual_series(fin, "EBIT", "Operating Income")
        interest = self._annual_series(
            fin, "Interest Expense", "Interest Expense Non Operating",
        )
        if not ebit or not interest:
            return None
        iexp = abs(interest[0])
        if iexp <= 0:
            return None
        return round(ebit[0] / iexp, 2)

    def _current_ratio(self, bal: object) -> Optional[float]:
        """Current Ratio = Current Assets / Current Liabilities."""
        ca = self._annual_series(
            bal, "Current Assets", "Total Current Assets",
        )
        cl = self._annual_series(
            bal, "Current Liabilities", "Total Current Liabilities",
        )
        if not ca or not cl or cl[0] <= 0:
            return None
        return round(ca[0] / cl[0], 2)

    def _fcf(self, cf: object) -> tuple[Optional[float], Optional[str]]:
        """
        Free Cash Flow = Operating Cash Flow - |Capital Expenditure|.
        Returns (latest_fcf_in_millions, trend_label).
        """
        ocf = self._annual_series(
            cf, "Operating Cash Flow", "Cash From Operations",
            "Cash Flowsfromusedin Operating Activities Direct",
        )
        capex = self._annual_series(
            cf, "Capital Expenditure",
            "Purchase Of Property Plant And Equipment",
            "Purchases Of Property Plant And Equipment",
        )
        if not ocf:
            return None, None

        fcf_series: list[float] = []
        for i, o in enumerate(ocf[:4]):
            cx = abs(capex[i]) if i < len(capex) else 0.0
            fcf_series.append(o - cx)

        latest = fcf_series[0] / 1_000_000  # convert to millions
        trend: Optional[str] = None
        if len(fcf_series) >= 2 and fcf_series[1] != 0:
            ratio = fcf_series[0] / fcf_series[1]
            trend = "growing" if ratio > 1.10 else "declining" if ratio < 0.90 else "stable"

        return round(latest, 2), trend

    def _de_trend(self, bal: object) -> Optional[str]:
        """D/E trend over available years: falling | stable | rising."""
        debt = self._annual_series(
            bal, "Total Debt", "Long Term Debt And Capital Lease Obligation",
            "Long Term Debt",
        )
        eq = self._annual_series(
            bal, "Stockholders Equity", "Common Stock Equity",
            "Total Stockholder Equity",
        )
        if len(debt) < 2 or len(eq) < 2:
            return None
        de_vals: list[float] = []
        for i in range(min(3, len(debt), len(eq))):
            if eq[i] > 0:
                de_vals.append(debt[i] / eq[i])
        if len(de_vals) < 2:
            return None
        if de_vals[0] < de_vals[-1] * 0.90:
            return "falling"
        if de_vals[0] > de_vals[-1] * 1.10:
            return "rising"
        return "stable"

    # ── Assembler ─────────────────────────────────────────────────────────────

    def _build(
        self,
        existing: Optional[FundamentalsData],
        main: dict,
        peer_rows: list[dict],
    ) -> FundamentalsData:
        info = main.get("info", {})
        fin  = main.get("financials")
        bal  = main.get("balance_sheet")
        cf   = main.get("cashflow")
        hist = main.get("price_history")

        # ── Growth CAGRs ──────────────────────────────────────────────────────
        rev_series = self._annual_series(fin, "Total Revenue", "Revenue")
        ni_series  = self._annual_series(fin, "Net Income")
        eps_series = self._annual_series(fin, "Basic EPS", "Diluted EPS")

        revenue_cagr_3y     = self._cagr_from_series(rev_series, 3)
        revenue_cagr_5y     = self._cagr_from_series(rev_series, 5)
        net_profit_cagr_3y  = self._cagr_from_series(ni_series,  3)
        net_profit_cagr_5y  = self._cagr_from_series(ni_series,  5)
        eps_cagr_3y         = self._cagr_from_series(eps_series, 3)

        # ── ROE historical average ────────────────────────────────────────────
        roe_hist = self._roe_history(fin, bal)
        roe_3y_avg = float(sum(roe_hist[:3]) / len(roe_hist[:3])) if len(roe_hist) >= 2 else None
        roe_5y_avg = float(sum(roe_hist[:5]) / len(roe_hist[:5])) if len(roe_hist) >= 3 else None

        # ── ROCE ─────────────────────────────────────────────────────────────
        roce_current = self._roce(info, fin, bal)

        # ── Historical P/E (own 5Y average) ──────────────────────────────────
        pe_hist = self._historical_pe(info, fin, hist)
        pe_5y_avg = float(sum(pe_hist) / len(pe_hist)) if len(pe_hist) >= 2 else None

        # ── Sector averages from peers ────────────────────────────────────────
        valid_peer_pes = [p["pe"] for p in peer_rows if p.get("pe") and 0 < p["pe"] < 500]
        valid_peer_pbs = [p["pb"] for p in peer_rows if p.get("pb") and 0 < p["pb"] < 200]
        pe_sector_avg = float(sum(valid_peer_pes) / len(valid_peer_pes)) if valid_peer_pes else None
        pb_sector_avg = float(sum(valid_peer_pbs) / len(valid_peer_pbs)) if valid_peer_pbs else None

        # ── Valuation signals ─────────────────────────────────────────────────
        current_pe       = _safe_float(info.get("trailingPE"))
        current_pb       = _safe_float(info.get("priceToBook"))
        current_ev_ebitda = _safe_float(info.get("enterpriseToEbitda"))

        pe_signal       = compute_valuation_signal(current_pe, pe_sector_avg, pe_5y_avg)
        pb_signal       = compute_valuation_signal(current_pb, pb_sector_avg, None)
        ev_ebitda_signal = compute_valuation_signal(current_ev_ebitda, None, None)
        valuation_class = compute_overall_valuation([pe_signal, pb_signal, ev_ebitda_signal])

        # ── Financial health ──────────────────────────────────────────────────
        interest_cov   = self._interest_coverage(fin)
        curr_ratio     = self._current_ratio(bal)
        fcf, fcf_trend = self._fcf(cf)
        de_trend       = self._de_trend(bal)

        # ── Peer models ───────────────────────────────────────────────────────
        peers = [
            PeerComparison(
                ticker=p["ticker"],
                name=p["name"],
                pe=p.get("pe"),
                pb=p.get("pb"),
                roe=p.get("roe"),
                revenue_growth=p.get("revenue_growth"),
                de_ratio=p.get("de_ratio"),
            )
            for p in peer_rows
        ] or None

        # ── Merge with existing basic fundamentals ────────────────────────────
        base: dict = existing.model_dump() if existing else {}
        return FundamentalsData(
            **{
                **base,
                "revenue_cagr_3y":        revenue_cagr_3y,
                "revenue_cagr_5y":        revenue_cagr_5y,
                "net_profit_cagr_3y":     net_profit_cagr_3y,
                "net_profit_cagr_5y":     net_profit_cagr_5y,
                "eps_cagr_3y":            eps_cagr_3y,
                "roe_3y_avg":             roe_3y_avg,
                "roe_5y_avg":             roe_5y_avg,
                "roce_current":           roce_current,
                "pe_5y_avg":              pe_5y_avg,
                "pe_sector_avg":          pe_sector_avg,
                "pb_sector_avg":          pb_sector_avg,
                "pe_signal":              pe_signal,
                "pb_signal":              pb_signal,
                "ev_ebitda_signal":       ev_ebitda_signal,
                "valuation_classification": valuation_class,
                "interest_coverage":      interest_cov,
                "current_ratio":          curr_ratio,
                "free_cash_flow":         fcf,
                "fcf_trend":              fcf_trend,
                "de_5y_trend":            de_trend,
                "peers":                  peers,
            }
        )
