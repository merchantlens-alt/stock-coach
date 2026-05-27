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
    },
    "required": [
        "why_it_gained", "key_catalysts", "catalyst_type",
        "sentiment", "is_sustained", "sustainability_reason", "confidence",
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
}


class GainerAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai
        self._model: Any = None

        if not self._mock:
            self._init_vertex()

    def _init_vertex(self) -> None:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(
            project=self._settings.google_cloud_project,
            location=self._settings.google_cloud_region,
        )
        self._model = GenerativeModel(
            self._settings.vertex_ai_model_flash,
            system_instruction=_SYSTEM_PROMPT,
        )
        log.info("gainer_analyst.vertex_ai_ready", model=self._settings.vertex_ai_model_flash)

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
        from vertexai.generative_models import GenerationConfig
        import asyncio

        headlines = "\n".join(f"- {n.title} ({n.source})" for n in news[:8])
        prompt = (
            f"Stock: {company_name} ({ticker})\n"
            f"Sector: {sector or 'Unknown'}\n"
            f"Today's gain: +{change_pct:.1f}%\n\n"
            f"Recent news headlines:\n{headlines or 'No news available.'}\n\n"
            "Analyse why this stock gained today and whether the momentum is likely to continue."
        )

        config = GenerationConfig(
            temperature=0.1,
            max_output_tokens=800,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        )

        response = await asyncio.to_thread(
            self._model.generate_content, prompt, generation_config=config
        )

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise AIAgentError(f"Gemini returned invalid JSON: {response.text[:200]}") from exc
