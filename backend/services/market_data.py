from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Optional

import yfinance as yf

from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, StockGainer, compute_quality_score

log = get_logger(__name__)

# ── Gemini + Google Search grounding response schema ─────────────────────────

_GAINERS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker":     {"type": "string"},
            "name":       {"type": "string"},
            "price":      {"type": "number"},
            "change_pct": {"type": "number"},
            "change_abs": {"type": "number"},
            "volume":     {"type": "number"},
            "sector":     {"type": "string"},
        },
        "required": ["ticker", "name", "price", "change_pct", "change_abs", "volume"],
    },
}

_US_PROMPT = """Use Google Search to find today's top US stock gainers right now.

Return the top 50 stocks with the highest percentage gain today.
Only include stocks that meet ALL of these criteria:
- Listed on NYSE or NASDAQ (not OTC, pink sheets, or foreign exchanges)
- Current stock price above $5
- Today's trading volume above 500,000 shares
- Ticker symbol is 5 characters or fewer
- Not a warrant, right, or unit (ticker does not end in W, R, or U)

Sort by percentage gain descending.
For each stock return: ticker, name, price, change_pct (number, e.g. 8.5 not "8.5%"),
change_abs (dollar change), volume (integer), sector (if known)."""

_INDIA_PROMPT = """Use Google Search to find today's top Indian stock gainers on NSE right now.

Return the top 50 NSE-listed stocks with the highest percentage gain today.
Only include stocks that meet ALL of these criteria:
- Listed on NSE (National Stock Exchange of India)
- Current stock price above ₹50
- Today's trading volume above 100,000 shares

Sort by percentage gain descending.
For each stock return: ticker (NSE symbol without .NS), name, price (in INR),
change_pct (number e.g. 8.5 not "8.5%"), change_abs, volume, sector (if known)."""


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
            raw = await self._fetch_gainers_via_gemini(_US_PROMPT, "us")
            gainers = self._build_gainers(raw, "us")
            log.info("market_data.us_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.us_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    async def get_india_gainers(self) -> list[StockGainer]:
        try:
            raw = await self._fetch_gainers_via_gemini(_INDIA_PROMPT, "india")
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

    # ── Gemini + Google Search grounding ──────────────────────────────────────

    async def _fetch_gainers_via_gemini(
        self, prompt: str, market: str
    ) -> list[dict[str, Any]]:
        import httpx

        token = await asyncio.to_thread(self._get_token)
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
                "responseMimeType": "application/json",
                "responseSchema": _GAINERS_SCHEMA,
            },
        }

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()

        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]

        try:
            result = json.loads(text)
            # Gemini may return a dict with an array inside or directly an array
            if isinstance(result, dict):
                result = result.get("items", result.get("stocks", result.get("gainers", [])))
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, KeyError) as exc:
            log.error("market_data.gemini_parse_error", error=str(exc), raw=text[:300])
            return []

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

    # ── yfinance for fundamentals (different endpoint, less rate-limited) ─────

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

    @staticmethod
    def _get_token() -> str:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token  # type: ignore[return-value]


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
