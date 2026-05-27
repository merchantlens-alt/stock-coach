from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import Market, MarketSummary, StockGainer

log = get_logger(__name__)

_SYSTEM_PROMPT = """You are a macro market analyst watching US and Indian stock markets.
Given today's top gainers, identify the themes and narrative behind the movement.
Write clearly for an intelligent non-professional investor.
Never say 'buy' or 'sell'. Focus on patterns, catalysts, and what to watch next.
Always respond in valid JSON matching the schema provided."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "string"}},
        "dominant_sector": {"type": "string"},
        "sentiment": {
            "type": "string",
            "enum": ["very_bullish", "bullish", "mixed", "bearish", "very_bearish"],
        },
        "watch_list": {"type": "array", "items": {"type": "string"}},
        "watch_reason": {"type": "string"},
    },
    "required": ["narrative", "themes", "sentiment", "watch_list", "watch_reason"],
}

_MOCK_RESPONSE: dict[str, Any] = {
    "narrative": (
        "Today's gainers are concentrated in AI infrastructure and semiconductor names, "
        "suggesting institutional rotation into high-growth tech ahead of upcoming earnings. "
        "The broad-based volume confirms this is not a single-stock event but a sector move."
    ),
    "themes": [
        "AI infrastructure demand",
        "Semiconductor supply chain recovery",
        "Earnings anticipation buying",
    ],
    "dominant_sector": "Technology",
    "sentiment": "bullish",
    "watch_list": ["NVDA", "AMD", "SMCI"],
    "watch_reason": (
        "Semiconductor names not yet in today's list may follow in 1–3 days "
        "as institutional rotation broadens out."
    ),
}


class MarketAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse(self, gainers: list[StockGainer], market: Market) -> MarketSummary:
        if self._mock:
            log.info("market_analyst.mock_response", market=market)
            return MarketSummary(market=market, **_MOCK_RESPONSE)

        raw = await self._call_gemini(gainers, market)
        try:
            return MarketSummary(market=market, **raw)
        except Exception as exc:
            raise AIAgentError(f"Invalid market analysis response: {exc}") from exc

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(self, gainers: list[StockGainer], market: str) -> dict[str, Any]:
        import asyncio
        import httpx

        market_label = "US" if market == "us" else "Indian (NSE)"
        lines = []
        for g in gainers:
            sector = f" [{g.sector}]" if g.sector else ""
            lines.append(f"- {g.ticker}{sector}: +{g.change_pct:.1f}% | ${g.price:.2f} | Vol {g.volume:,}")

        prompt = (
            f"Today's top {len(gainers)} gainers in the {market_label} market:\n\n"
            + "\n".join(lines)
            + "\n\nWhat macro/sector themes are driving today's movement? "
            "What does this signal about market sentiment? "
            "Which related stocks or sectors should investors watch next?"
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 600,
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
            },
        }

        token = await asyncio.to_thread(self._get_token)
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()

        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIAgentError(f"Gemini returned invalid JSON: {text[:200]}") from exc

    @staticmethod
    def _get_token() -> str:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token  # type: ignore[return-value]
