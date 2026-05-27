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

# NOTE: responseSchema / responseMimeType are intentionally NOT used here.
# Vertex AI does not allow JSON-mode (controlled generation) and googleSearch
# grounding in the same request. Instead, we embed format instructions in the
# prompt and extract JSON robustly from the plain-text response.

_JSON_FORMAT_HINT = """
Respond with a raw JSON array only — no prose, no markdown, no code fences.
Each element must be a JSON object with these keys:
  ticker      (string)  – exchange symbol, e.g. "NVDA"
  name        (string)  – company display name
  price       (number)  – current price
  change_pct  (number)  – percentage gain as a plain number, e.g. 8.5 not "8.5%"
  change_abs  (number)  – absolute price change
  volume      (number)  – today's trading volume (integer)
  sector      (string, optional) – e.g. "Technology"

Example:
[{"ticker":"NVDA","name":"NVIDIA Corporation","price":950.0,"change_pct":8.5,"change_abs":74.5,"volume":45000000,"sector":"Technology"}]"""

_US_PROMPT = (
    "Use Google Search to find today's top US stock gainers right now.\n\n"
    "Return the top 50 stocks with the highest percentage gain today.\n"
    "Only include stocks that meet ALL of these criteria:\n"
    "- Listed on NYSE or NASDAQ (not OTC, pink sheets, or foreign exchanges)\n"
    "- Current stock price above $5\n"
    "- Today's trading volume above 500,000 shares\n"
    "- Ticker symbol is 5 characters or fewer\n"
    "- Not a warrant, right, or unit (ticker does not end in W, R, or U)\n\n"
    "Sort by percentage gain descending.\n"
    + _JSON_FORMAT_HINT
)

_INDIA_PROMPT = (
    "Use Google Search to find today's top Indian stock gainers on NSE right now.\n\n"
    "Return the top 50 NSE-listed stocks with the highest percentage gain today.\n"
    "Only include stocks that meet ALL of these criteria:\n"
    "- Listed on NSE (National Stock Exchange of India)\n"
    "- Current stock price above ₹50\n"
    "- Today's trading volume above 100,000 shares\n\n"
    "Sort by percentage gain descending.\n"
    "Use the NSE ticker symbol WITHOUT the .NS suffix.\n"
    "Use INR for price and change_abs.\n"
    + _JSON_FORMAT_HINT
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

        # IMPORTANT: responseMimeType / responseSchema must NOT be set when
        # googleSearch grounding is enabled — Vertex AI rejects that combination
        # with a 400 error.  JSON format is enforced via the prompt instead.
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
                    "market_data.gemini_http_error",
                    status=resp.status_code,
                    body=resp.text[:400],
                )
            resp.raise_for_status()

        data = resp.json()
        # Grounded responses may span multiple parts; join them all
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

        return _extract_json_list(text)

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


def _extract_json_list(text: str) -> list[dict[str, Any]]:
    """
    Extract a JSON array from a Gemini response that may contain surrounding
    prose, markdown fences, or grounding citations.

    Strategy (in order):
      1. Direct parse — the whole text is valid JSON.
      2. Unwrap a single dict wrapper like {"gainers": [...]} or {"items": [...]}.
      3. Regex-extract the first [...] block from mixed prose + JSON.
    """
    import re

    def _unwrap(obj: Any) -> list[dict[str, Any]]:
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ("gainers", "stocks", "items", "data", "results"):
                if key in obj and isinstance(obj[key], list):
                    return obj[key]
        return []

    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()

    # Attempt 1: direct parse
    try:
        return _unwrap(json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract the first JSON array block from prose
    match = re.search(r"\[\s*\{.*?\}\s*\]", cleaned, re.DOTALL)
    if match:
        try:
            return _unwrap(json.loads(match.group()))
        except json.JSONDecodeError:
            pass

    log.warning("market_data.gemini_parse_failed", preview=text[:300])
    return []


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
