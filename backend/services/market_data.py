from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Optional

import yfinance as yf

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import MarketDataError, TickerNotFoundError
from core.logging import get_logger
from models.schemas import FundamentalsData, Market, StockGainer, compute_quality_score

log = get_logger(__name__)

# ── Step 1: Google Search grounding prompts (natural language — no JSON) ───────

_US_SEARCH_PROMPT = (
    "Use Google Search to find today's top US stock gainers right now.\n\n"
    "List the top 50 stocks with the highest percentage gain today on NYSE or NASDAQ.\n"
    "For each stock include: ticker symbol, company name, current price, "
    "percentage gain, absolute price change, trading volume, and sector.\n"
    "Only include stocks priced above $5 with volume above 500,000 shares. "
    "Exclude warrants, rights, units (tickers ending in W, R, or U). "
    "Ticker must be 5 characters or fewer."
)

_INDIA_SEARCH_PROMPT = (
    "Use Google Search to find today's top Indian stock gainers on NSE right now.\n\n"
    "List the top 50 NSE-listed stocks with the highest percentage gain today.\n"
    "For each stock include: NSE ticker symbol (without .NS suffix), company name, "
    "current price in INR, percentage gain, absolute price change in INR, "
    "trading volume, and sector.\n"
    "Only include stocks priced above ₹50 with volume above 100,000 shares."
)

# ── Step 2: responseSchema for structured JSON output (no googleSearch) ────────

_GAINERS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker":      {"type": "string"},
            "name":        {"type": "string"},
            "price":       {"type": "number"},
            "change_pct":  {"type": "number"},
            "change_abs":  {"type": "number"},
            "volume":      {"type": "integer"},
            "sector":      {"type": "string"},
        },
        "required": ["ticker", "name", "price", "change_pct", "change_abs", "volume"],
    },
}

_STRUCTURE_PROMPT_TEMPLATE = (
    "Convert the following stock market data into a structured JSON array.\n"
    "Extract every stock mentioned and output the required fields.\n"
    "Use the exact ticker symbols as given. "
    "If sector is not mentioned for a stock, omit that field.\n\n"
    "Market data:\n{raw_text}"
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
            raw = await self._fetch_gainers_via_gemini(_US_SEARCH_PROMPT, "us")
            gainers = self._build_gainers(raw, "us")
            log.info("market_data.us_gainers_fetched", count=len(gainers))
            return gainers[: self._top_n]
        except Exception as exc:
            log.error("market_data.us_gainers_error", error=str(exc))
            raise MarketDataError(f"Failed to fetch US gainers: {exc}") from exc

    async def get_india_gainers(self) -> list[StockGainer]:
        try:
            raw = await self._fetch_gainers_via_gemini(_INDIA_SEARCH_PROMPT, "india")
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

    # ── Two-step Gemini pipeline ──────────────────────────────────────────────

    async def _fetch_gainers_via_gemini(
        self, search_prompt: str, market: str
    ) -> list[dict[str, Any]]:
        """
        Two-step pipeline:
          Step 1 — Google Search grounding: ask Gemini to search live market data
                   and return a natural-language summary (no responseSchema).
          Step 2 — Structured extraction: ask Gemini (no grounding) to convert
                   the prose into a typed JSON array using responseSchema.

        Vertex AI rejects requests that combine googleSearch grounding with
        responseMimeType / responseSchema in the same call (returns HTTP 400).
        Splitting into two calls sidesteps this limitation completely.
        """
        token = await asyncio.to_thread(get_cached_token)

        # Step 1: live search → prose text
        raw_text = await self._ground_search(token, search_prompt, market)
        if not raw_text.strip():
            log.warning("market_data.ground_search_empty", market=market)
            return []

        log.debug("market_data.ground_search_done", market=market, chars=len(raw_text))

        # Step 2: prose → structured JSON
        return await self._structure_gainers_to_json(token, raw_text, market)

    async def _ground_search(
        self, token: str, prompt: str, market: str
    ) -> str:
        """Call Gemini with googleSearch grounding. Returns raw prose text."""
        import httpx

        url = self._vertex_url(self._settings.vertex_ai_model_flash)
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 4096,
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            if not resp.is_success:
                log.error(
                    "market_data.ground_search_http_error",
                    market=market,
                    status=resp.status_code,
                    body=resp.text[:400],
                )
            resp.raise_for_status()

        data = resp.json()
        parts = data["candidates"][0]["content"].get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    async def _structure_gainers_to_json(
        self, token: str, raw_text: str, market: str
    ) -> list[dict[str, Any]]:
        """Call Gemini with responseSchema (no grounding) to convert prose → JSON array."""
        import httpx

        prompt = _STRUCTURE_PROMPT_TEMPLATE.format(raw_text=raw_text)
        url = self._vertex_url(self._settings.vertex_ai_model_flash)
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 8192,
                "responseMimeType": "application/json",
                "responseSchema": _GAINERS_SCHEMA,
            },
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            if not resp.is_success:
                log.error(
                    "market_data.structure_json_http_error",
                    market=market,
                    status=resp.status_code,
                    body=resp.text[:400],
                )
            resp.raise_for_status()

        data = resp.json()
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            log.warning("market_data.structure_json_not_list", market=market, preview=text[:200])
            return []
        except json.JSONDecodeError:
            log.warning("market_data.structure_json_parse_failed", market=market, preview=text[:300])
            return []

    def _vertex_url(self, model: str) -> str:
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        return (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

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
