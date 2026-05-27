from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any, Optional

import httpx
import yfinance as yf

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, StockGainer, compute_quality_score

log = get_logger(__name__)

# ── Yahoo Finance search (company name → ticker) ───────────────────────────────
_YF_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_US_EXCHANGES = {"NMS", "NYQ", "NGM", "PCX", "BATS", "ASE", "OPR"}

# ── Gemini + Google Search prompts ────────────────────────────────────────────
# We ask Gemini to output a pipe-delimited table instead of JSON.
# Reason: Vertex AI blocks responseSchema when googleSearch grounding is active
# (returns HTTP 400). Prose is hard to parse. Pipe-delimited text is easy to
# parse deterministically in Python with no second AI call needed.

_TABLE_FORMAT = """
Output ONLY a pipe-delimited data table — no headers, no prose, no markdown.
One stock per line in this exact format:
TICKER|NAME|PRICE|CHANGE_PCT|CHANGE_ABS|VOLUME|SECTOR

Example:
ASTC|Astrotech Corporation|6.55|165.2|4.08|500000|Industrials
NVDA|NVIDIA Corporation|950.00|8.5|74.50|45000000|Technology

Output at least 20 stocks. Sort by CHANGE_PCT descending."""

_US_PROMPT = (
    "Use Google Search to find today's top 50 US stock gainers on NYSE and NASDAQ right now.\n\n"
    "Only include stocks where ALL of these are true:\n"
    "- Listed on NYSE or NASDAQ (not OTC or pink sheets)\n"
    "- Current price above $5\n"
    "- Today's trading volume above 500,000 shares\n"
    "- Ticker symbol is 5 characters or fewer\n"
    "- Not a warrant/right/unit (ticker does not end in W, R, or U)\n\n"
    + _TABLE_FORMAT
)

_INDIA_PROMPT = (
    "Use Google Search to find today's top 50 NSE (National Stock Exchange of India) "
    "stock gainers right now.\n\n"
    "Only include stocks where ALL of these are true:\n"
    "- Listed on NSE India\n"
    "- Current price above ₹50\n"
    "- Today's trading volume above 100,000 shares\n\n"
    "Use the NSE ticker symbol WITHOUT the .NS suffix.\n"
    "Use INR values for PRICE and CHANGE_ABS.\n\n"
    + _TABLE_FORMAT
)


class MarketDataService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._top_n = settings.top_gainers_count

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_gainers(self, market: Market) -> list[StockGainer]:
        if market == "us":
            return await self.get_us_gainers()
        return await self.get_india_gainers()

    async def get_us_gainers(self) -> list[StockGainer]:
        try:
            raw = await self._fetch_gainers_gemini(_US_PROMPT, "us")
            gainers = self._build_gainers(raw, "us")
            log.info("market_data.us_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.us_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    async def get_india_gainers(self) -> list[StockGainer]:
        try:
            raw = await self._fetch_gainers_gemini(_INDIA_PROMPT, "india")
            gainers = self._build_gainers(raw, "india")
            log.info("market_data.india_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.india_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch India gainers: {exc}") from exc

    async def get_fundamentals(self, ticker: str, market: Market) -> FundamentalsData:
        yf_ticker = f"{ticker}.NS" if market == "india" else ticker
        try:
            data = await asyncio.to_thread(self._fetch_fundamentals_sync, yf_ticker)
            return data
        except Exception as exc:
            log.error("market_data.fundamentals_error", ticker=ticker, error=str(exc))
            raise MarketDataError(f"Failed to fetch fundamentals for {ticker}: {exc}") from exc

    # ── Gemini + Google Search (pipe-delimited table) ─────────────────────────

    async def _fetch_gainers_gemini(
        self, prompt: str, market: str
    ) -> list[dict[str, Any]]:
        """
        Ask Gemini (with Google Search grounding) to return a pipe-delimited
        table of today's top gainers.

        Why pipe-delimited instead of JSON?
        Vertex AI rejects requests combining googleSearch grounding with
        responseMimeType/responseSchema (HTTP 400). Prose is unpredictable.
        Pipe-delimited text is structured enough for Gemini to produce
        consistently and trivial to parse in Python — no second AI call needed.
        """
        token = await asyncio.to_thread(get_cached_token)
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 4096,
                # NOTE: responseMimeType / responseSchema intentionally omitted —
                # Vertex AI returns HTTP 400 when combined with googleSearch.
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            if not resp.is_success:
                log.error(
                    "market_data.gemini_http_error",
                    market=market,
                    status=resp.status_code,
                    body=resp.text[:400],
                )
            resp.raise_for_status()

        data = resp.json()
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

        log.debug("market_data.gemini_raw", market=market, chars=len(text), preview=text[:300])
        return _parse_pipe_table(text)

    # ── Builder ───────────────────────────────────────────────────────────────

    def _build_gainers(
        self, raw: list[dict[str, Any]], market: Market
    ) -> list[StockGainer]:
        gainers: list[StockGainer] = []
        for q in raw:
            try:
                ticker = str(q.get("ticker", "")).upper().strip()
                if not ticker:
                    continue
                price = float(q.get("price", 0))
                volume = int(q.get("volume", 0))
                change_pct = float(q.get("change_pct", 0))
                if change_pct <= 0:
                    continue

                score, label = compute_quality_score(price, volume, change_pct, ticker)
                gainers.append(
                    StockGainer(
                        ticker=ticker,
                        name=str(q.get("name", ticker)),
                        market=market,
                        price=price,
                        change_pct=round(change_pct, 2),
                        change_abs=float(q.get("change_abs", 0)),
                        volume=volume,
                        sector=q.get("sector"),
                        quality_score=score,
                        quality_label=label,
                    )
                )
            except Exception:
                continue

        return sorted(gainers, key=lambda g: g.change_pct, reverse=True)

    # ── yfinance for fundamentals ─────────────────────────────────────────────

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


def _parse_pipe_table(text: str) -> list[dict[str, Any]]:
    """
    Parse Gemini's pipe-delimited table response into a list of stock dicts.

    Expected line format (Gemini is instructed to produce this):
      TICKER|NAME|PRICE|CHANGE_PCT|CHANGE_ABS|VOLUME|SECTOR

    Tolerant of:
    - Extra whitespace / blank lines
    - Missing SECTOR column
    - Header lines (skipped if TICKER is non-numeric and PRICE is non-numeric)
    - Markdown table separators (---)
    """
    results: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        # Skip markdown separators like |---|---|
        if re.match(r"^[\s|:\-]+$", line):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue

        ticker = parts[0].upper()
        name = parts[1]
        price_str = parts[2]
        change_pct_str = parts[3]
        change_abs_str = parts[4]
        volume_str = parts[5]
        sector = parts[6] if len(parts) > 6 else None

        # Skip header rows (price field is not numeric)
        try:
            price = float(price_str.replace(",", "").replace("$", "").replace("₹", ""))
            change_pct = float(change_pct_str.replace("%", "").replace("+", ""))
            change_abs = float(change_abs_str.replace(",", "").replace("$", "").replace("₹", ""))
            volume = int(volume_str.replace(",", "").replace(".", ""))
        except (ValueError, AttributeError):
            continue  # header row or malformed — skip

        if not ticker or not ticker.isalpha():
            continue

        results.append({
            "ticker": ticker,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "change_abs": change_abs,
            "volume": volume,
            "sector": sector if sector else None,
        })

    log.debug("market_data.pipe_table_parsed", rows=len(results))
    return results


async def resolve_ticker_by_name(query: str, market: Market) -> str | None:
    """
    Resolve a company name (e.g. "NVIDIA") to its ticker (e.g. "NVDA")
    via Yahoo Finance search. Called as fallback when direct ticker lookup fails.
    """
    params = {
        "q": query,
        "quotesCount": 8,
        "newsCount": 0,
        "listsCount": 0,
        "enableFuzzyQuery": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(_YF_SEARCH_URL, params=params, headers=_YF_HEADERS)
            resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
    except Exception as exc:
        log.warning("market_data.name_resolve_failed", query=query, error=str(exc))
        return None

    for q in quotes:
        if q.get("quoteType") != "EQUITY":
            continue
        symbol: str = q.get("symbol", "")
        exchange: str = q.get("exchange", "")

        if market == "india":
            if symbol.endswith(".NS"):
                return symbol[:-3]
            if symbol.endswith(".BO"):
                return symbol[:-3]
            if exchange in ("NSE", "BSE"):
                return symbol
        else:
            if "." not in symbol and len(symbol) <= 5 and exchange in _US_EXCHANGES:
                return symbol
            if "." not in symbol and len(symbol) <= 5 and not exchange:
                return symbol

    return None


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
