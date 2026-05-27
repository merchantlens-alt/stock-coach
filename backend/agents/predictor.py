from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import FundamentalsData, GainerAnalysis, StockPrediction

log = get_logger(__name__)

_SYSTEM_PROMPT = """You are a fundamental analysis agent for stocks.
Given a stock's financials, recent gain, and the catalyst that drove it,
predict whether the stock can continue growing over the next 30 days.
Write your outlook in plain English for a beginner investor.
Be honest about uncertainty — never overstate confidence.
Never use the words 'buy' or 'sell'. Only describe what the data suggests.
Always respond in valid JSON matching the schema provided."""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "outlook": {"type": "string"},
        "predicted_change_pct": {"type": "number"},
        "confidence": {"type": "number"},
        "time_horizon": {"type": "string", "enum": ["days", "weeks", "months"]},
        "key_risks": {"type": "array", "items": {"type": "string"}},
        "key_tailwinds": {"type": "array", "items": {"type": "string"}},
        "valuation_signal": {
            "type": "string",
            "enum": ["undervalued", "fairly_valued", "overvalued", "unknown"],
        },
        "growth_signal": {
            "type": "string",
            "enum": ["strong", "moderate", "weak", "unknown"],
        },
        "debt_signal": {
            "type": "string",
            "enum": ["strong", "moderate", "weak", "unknown"],
        },
    },
    "required": [
        "outlook", "predicted_change_pct", "confidence", "time_horizon",
        "key_risks", "key_tailwinds", "valuation_signal", "growth_signal", "debt_signal",
    ],
}

_MOCK_RESPONSE: dict[str, Any] = {
    "outlook": (
        "Based on strong earnings and raised guidance, this stock has a reasonable chance of "
        "continued momentum over the next few weeks. The earnings beat removes near-term "
        "uncertainty and institutional investors often continue accumulating after such results. "
        "However, the stock has already priced in much of the good news with today's surge, "
        "so further upside may be more moderate."
    ),
    "predicted_change_pct": 4.5,
    "confidence": 0.60,
    "time_horizon": "weeks",
    "key_risks": [
        "Stock already up sharply — good news may be fully priced in",
        "Broader market correction could drag it down regardless of fundamentals",
        "Elevated expectations leave little room for the next earnings miss",
    ],
    "key_tailwinds": [
        "Earnings momentum typically sustains 2–4 weeks post-results",
        "Raised guidance reduces downside risk",
        "Analyst price target upgrades likely to follow",
    ],
    "valuation_signal": "fairly_valued",
    "growth_signal": "strong",
    "debt_signal": "moderate",
}

_DISCLAIMER = (
    "This is AI-generated analysis for educational purposes only. "
    "It is not investment advice under any regulatory framework. "
    "Past AI analysis performance does not guarantee future accuracy. "
    "Always consult a registered financial advisor before making investment decisions."
)


class PredictorAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def predict(
        self,
        ticker: str,
        company_name: str,
        fundamentals: FundamentalsData,
        analysis: GainerAnalysis,
    ) -> StockPrediction:
        if self._mock:
            log.info("predictor.mock_response", ticker=ticker)
            return StockPrediction(ticker=ticker, disclaimer=_DISCLAIMER, **_MOCK_RESPONSE)

        raw = await self._call_gemini(ticker, company_name, fundamentals, analysis)
        try:
            return StockPrediction(ticker=ticker, disclaimer=_DISCLAIMER, **raw)
        except Exception as exc:
            raise AIAgentError(f"Invalid predictor AI response for {ticker}: {exc}") from exc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_gemini(
        self,
        ticker: str,
        company_name: str,
        fundamentals: FundamentalsData,
        analysis: GainerAnalysis,
    ) -> dict[str, Any]:
        import asyncio
        import httpx

        fund_text = _format_fundamentals(fundamentals)
        prompt = (
            f"Stock: {company_name} ({ticker})\n\n"
            f"FUNDAMENTALS:\n{fund_text}\n\n"
            f"TODAY'S CATALYST:\n"
            f"- Gain today: {analysis.confidence:.0%} confidence\n"
            f"- Catalyst type: {analysis.catalyst_type}\n"
            f"- Why it gained: {analysis.why_it_gained}\n"
            f"- Key catalysts: {', '.join(analysis.key_catalysts)}\n"
            f"- Sustained momentum likely: {analysis.is_sustained}\n\n"
            "Based on these fundamentals and the catalyst, predict the 30-day outlook."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1000,
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
            },
        }

        token = await asyncio.to_thread(self._get_token)
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_pro
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        async with httpx.AsyncClient(timeout=60) as client:
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


def _format_fundamentals(f: FundamentalsData) -> str:
    lines = []
    if f.pe_ratio is not None:
        lines.append(f"- P/E ratio: {f.pe_ratio:.1f}")
    if f.forward_pe is not None:
        lines.append(f"- Forward P/E: {f.forward_pe:.1f}")
    if f.roe is not None:
        lines.append(f"- Return on equity: {f.roe:.1%}")
    if f.debt_equity is not None:
        lines.append(f"- Debt/equity: {f.debt_equity:.2f}")
    if f.revenue_growth_yoy is not None:
        lines.append(f"- Revenue growth YoY: {f.revenue_growth_yoy:.1%}")
    if f.earnings_growth_yoy is not None:
        lines.append(f"- Earnings growth YoY: {f.earnings_growth_yoy:.1%}")
    if f.profit_margin is not None:
        lines.append(f"- Profit margin: {f.profit_margin:.1%}")
    if f.analyst_recommendation:
        lines.append(f"- Analyst consensus: {f.analyst_recommendation}")
    if f.analyst_target_price:
        lines.append(f"- Analyst target price: {f.analyst_target_price:.2f}")
    return "\n".join(lines) if lines else "No fundamental data available."
