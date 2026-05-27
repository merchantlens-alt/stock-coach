from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import GainerAnalysis, NewsItem

log = get_logger(__name__)

_SYSTEM_PROMPT = """You are a financial analyst specialising in explaining why stocks move.
Given a stock's recent price gain and news headlines, explain the likely catalyst clearly.
Write for a beginner investor — no jargon without explanation.
Never recommend buying or selling. Only describe what happened and why.
Identify related stocks that may benefit from the same catalyst.
Always respond in valid JSON matching the schema provided."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "why_it_gained": {"type": "string"},
        "key_catalysts": {"type": "array", "items": {"type": "string"}},
        "catalyst_type": {
            "type": "string",
            "enum": [
                "earnings", "fda_approval", "acquisition", "partnership",
                "analyst_upgrade", "macro", "technical", "regulatory", "unknown",
            ],
        },
        "sentiment": {
            "type": "string",
            "enum": ["very_positive", "positive", "neutral", "negative", "very_negative"],
        },
        "is_sustained": {"type": "boolean"},
        "sustainability_reason": {"type": "string"},
        "confidence": {"type": "number"},
        "related_beneficiaries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ticker symbols of other stocks likely to benefit from the same catalyst",
        },
        "beneficiary_reasoning": {
            "type": "string",
            "description": "Why these related stocks may follow",
        },
    },
    "required": [
        "why_it_gained", "key_catalysts", "catalyst_type",
        "sentiment", "is_sustained", "sustainability_reason", "confidence",
        "related_beneficiaries", "beneficiary_reasoning",
    ],
}

_MOCK_RESPONSE: dict[str, Any] = {
    "why_it_gained": (
        "The stock surged following stronger-than-expected earnings results. "
        "Revenue beat analyst estimates by 8% and the company raised its full-year guidance, "
        "signalling management's confidence in continued growth."
    ),
    "key_catalysts": [
        "Earnings beat analyst estimates by 8%",
        "Full-year guidance raised",
        "Management cited strong demand environment",
    ],
    "catalyst_type": "earnings",
    "sentiment": "very_positive",
    "is_sustained": True,
    "sustainability_reason": (
        "Earnings beats with raised guidance typically sustain momentum over weeks "
        "as institutional investors revalue the stock upward."
    ),
    "confidence": 0.78,
    "related_beneficiaries": ["AMD", "SMCI", "AVGO"],
    "beneficiary_reasoning": (
        "AMD and AVGO operate in the same semiconductor supply chain and often follow "
        "NVDA-driven sector rotations. SMCI benefits directly from AI server demand."
    ),
}


class GainerAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse(
        self,
        ticker: str,
        change_pct: float,
        company_name: str,
        sector: str | None,
        news: list[NewsItem],
    ) -> GainerAnalysis:
        if self._mock:
            log.info("gainer_analyst.mock_response", ticker=ticker)
            return GainerAnalysis(ticker=ticker, **_MOCK_RESPONSE)

        raw = await self._call_gemini(ticker, change_pct, company_name, sector, news)
        try:
            return GainerAnalysis(ticker=ticker, **raw)
        except Exception as exc:
            raise AIAgentError(f"Invalid AI response for {ticker}: {exc}") from exc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_gemini(
        self,
        ticker: str,
        change_pct: float,
        company_name: str,
        sector: str | None,
        news: list[NewsItem],
    ) -> dict[str, Any]:
        import asyncio
        import httpx
        import google.auth
        import google.auth.transport.requests

        headlines = "\n".join(f"- {n.title} ({n.source})" for n in news[:8])
        prompt = (
            f"Stock: {company_name} ({ticker})\n"
            f"Sector: {sector or 'Unknown'}\n"
            f"Today's gain: +{change_pct:.1f}%\n\n"
            f"Recent news headlines:\n{headlines or 'No news available.'}\n\n"
            "Analyse why this stock gained today and whether the momentum is likely to continue. "
            "Also identify 2-4 related ticker symbols that may benefit from the same catalyst."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800,
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

        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
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
