from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

import yfinance as yf

from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, StockGainer

log = get_logger(__name__)

# Nifty 100 tickers — top Indian stocks by market cap on NSE
NIFTY_100_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFOSYS.NS",
    "HINDUNILVR.NS", "BHARTIARTL.NS", "SBIN.NS", "BAJFINANCE.NS", "KOTAKBANK.NS",
    "LICI.NS", "HCLTECH.NS", "WIPRO.NS", "ULTRACEMCO.NS", "ITC.NS",
    "ADANIENT.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "ONGC.NS",
    "NTPC.NS", "POWERGRID.NS", "BAJAJFINSV.NS", "M&M.NS", "TECHM.NS",
    "NESTLEIND.NS", "ASIANPAINT.NS", "LTIM.NS", "HINDALCO.NS", "JSWSTEEL.NS",
    "TATAMOTORS.NS", "AXISBANK.NS", "COALINDIA.NS", "DRREDDY.NS", "BAJAJ-AUTO.NS",
    "GRASIM.NS", "CIPLA.NS", "BRITANNIA.NS", "TATACONSUM.NS", "HEROMOTOCO.NS",
    "BPCL.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "EICHERMOT.NS", "SHREECEM.NS",
    "ADANIPORTS.NS", "SBILIFE.NS", "HDFCLIFE.NS", "PIDILITIND.NS", "GODREJCP.NS",
    "BERGEPAINT.NS", "NAUKRI.NS", "MUTHOOTFIN.NS", "LTTS.NS", "MPHASIS.NS",
    "COFORGE.NS", "PERSISTENT.NS", "TRENT.NS", "VEDL.NS", "JINDALSTEL.NS",
    "NMDC.NS", "TORNTPHARM.NS", "AUROPHARMA.NS", "ALKEM.NS", "BIOCON.NS",
    "ABBOTINDIA.NS", "GLAXO.NS", "PFIZER.NS", "ZYDUSLIFE.NS", "LALPATHLAB.NS",
    "FORTIS.NS", "POLYCAB.NS", "SUPREMEIND.NS", "ASTRAL.NS", "HAVELLS.NS",
    "CROMPTON.NS", "VOLTAS.NS", "DMART.NS", "ZOMATO.NS", "NYKAA.NS",
    "IRCTC.NS", "CAMS.NS", "CDSL.NS", "MCX.NS", "INDIGO.NS",
    "TATASTEEL.NS", "SAIL.NS", "HINDPETRO.NS", "IOC.NS", "GAIL.NS",
    "BANKBARODA.NS", "CANBK.NS", "PNB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS",
    "IDFCFIRSTB.NS", "AUBANK.NS", "RBLBANK.NS", "CHOLAFIN.NS", "BAJAJHLDNG.NS",
]


class MarketDataService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._top_n = settings.top_gainers_count

    async def get_us_gainers(self) -> list[StockGainer]:
        """Fetch top US gainers using the yfinance built-in screener."""
        try:
            gainers = await asyncio.to_thread(self._fetch_us_gainers_sync)
            log.info("market_data.us_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.us_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    def _fetch_us_gainers_sync(self) -> list[StockGainer]:
        screener = yf.Screener()
        screener.set_predefined_screener("day_gainers")

        # yfinance >= 0.2.40: use .quotes (DataFrame), not .df
        try:
            df = screener.quotes
        except Exception:
            df = None

        # Fallback: try .body directly
        if df is None or (hasattr(df, "empty") and df.empty):
            try:
                quotes = screener.body.get("quotes", [])
                if not quotes:
                    return []
                import pandas as pd
                df = pd.DataFrame(quotes)
            except Exception:
                return []

        if df is None or df.empty:
            return []

        gainers: list[StockGainer] = []
        for _, row in df.iterrows():
            change_pct = row.get("regularMarketChangePercent", 0)
            if not change_pct or float(change_pct) <= 0:
                continue
            try:
                gainers.append(
                    StockGainer(
                        ticker=str(row.get("symbol", "")),
                        name=str(row.get("shortName", row.get("symbol", ""))),
                        market="us",
                        price=float(row.get("regularMarketPrice", 0)),
                        change_pct=float(change_pct),
                        change_abs=float(row.get("regularMarketChange", 0)),
                        volume=int(row.get("regularMarketVolume", 0)),
                        avg_volume=_safe_int(row.get("averageDailyVolume3Month")),
                        market_cap=_safe_float(row.get("marketCap")),
                        sector=row.get("sector"),
                        industry=row.get("industry"),
                    )
                )
            except Exception:
                continue

        return sorted(gainers, key=lambda g: g.change_pct, reverse=True)

    async def get_india_gainers(self) -> list[StockGainer]:
        """Fetch top NSE gainers by scanning the Nifty 100 universe."""
        try:
            gainers = await asyncio.to_thread(self._fetch_india_gainers_sync)
            log.info("market_data.india_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.india_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch India gainers: {exc}") from exc

    def _fetch_india_gainers_sync(self) -> list[StockGainer]:
        # Batch download in chunks to avoid rate limits
        chunk_size = 20
        gainers: list[StockGainer] = []

        for i in range(0, len(NIFTY_100_TICKERS), chunk_size):
            chunk = NIFTY_100_TICKERS[i : i + chunk_size]
            try:
                tickers = yf.Tickers(" ".join(chunk))
                for symbol in chunk:
                    info = tickers.tickers.get(symbol, {})
                    if not hasattr(info, "info"):
                        continue
                    d = info.info
                    change_pct = d.get("regularMarketChangePercent", 0)
                    if not change_pct or change_pct <= 0:
                        continue
                    try:
                        # Strip .NS suffix for display
                        display_ticker = symbol.replace(".NS", "")
                        gainers.append(
                            StockGainer(
                                ticker=display_ticker,
                                name=str(d.get("shortName", display_ticker)),
                                market="india",
                                price=float(d.get("regularMarketPrice", 0)),
                                change_pct=float(change_pct),
                                change_abs=float(d.get("regularMarketChange", 0)),
                                volume=int(d.get("regularMarketVolume", 0)),
                                avg_volume=_safe_int(d.get("averageDailyVolume3Month")),
                                market_cap=_safe_float(d.get("marketCap")),
                                sector=d.get("sector"),
                                industry=d.get("industry"),
                            )
                        )
                    except Exception:
                        continue
            except Exception as exc:
                log.warning("market_data.india_chunk_error", chunk=chunk, error=str(exc))

        return sorted(gainers, key=lambda g: g.change_pct, reverse=True)

    async def get_fundamentals(self, ticker: str, market: Market) -> FundamentalsData:
        """Fetch fundamental data for a single ticker."""
        yf_ticker = f"{ticker}.NS" if market == "india" else ticker
        try:
            data = await asyncio.to_thread(self._fetch_fundamentals_sync, yf_ticker)
            return data
        except Exception as exc:
            log.error("market_data.fundamentals_error", ticker=ticker, error=str(exc))
            raise MarketDataError(f"Failed to fetch fundamentals for {ticker}: {exc}") from exc

    def _fetch_fundamentals_sync(self, yf_ticker: str) -> FundamentalsData:
        info = yf.Ticker(yf_ticker).info
        if not info:
            raise TickerNotFoundError(yf_ticker)
        return FundamentalsData(
            pe_ratio=_safe_float(info.get("trailingPE")),
            forward_pe=_safe_float(info.get("forwardPE")),
            roe=_safe_float(info.get("returnOnEquity")),
            debt_equity=_safe_float(info.get("debtToEquity")),
            revenue_growth_yoy=_safe_float(info.get("revenueGrowth")),
            earnings_growth_yoy=_safe_float(info.get("earningsGrowth")),
            profit_margin=_safe_float(info.get("profitMargins")),
            fifty_two_week_high=_safe_float(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_safe_float(info.get("fiftyTwoWeekLow")),
            analyst_target_price=_safe_float(info.get("targetMeanPrice")),
            analyst_recommendation=info.get("recommendationKey"),
        )

    async def get_gainers(self, market: Market) -> list[StockGainer]:
        if market == "us":
            return await self.get_us_gainers()
        return await self.get_india_gainers()


def _safe_float(v: object) -> Optional[float]:
    try:
        return float(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> Optional[int]:
    try:
        return int(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def today_str() -> str:
    return date.today().isoformat()
