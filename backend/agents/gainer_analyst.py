"""
GainerAnalystAgent — single Gemini call that returns both the why-it-gained
analysis AND the 30-day prediction in one shot.

Speed rationale
───────────────
The original design made two sequential Gemini calls (analyst then predictor).
Each call took 8-15 s, making a cold analysis 20-30 s total.  Merging them into
one call cuts AI latency by ~40-50 % because:
  1. Only one round-trip to Vertex AI instead of two.
  2. The combined model has full context for both tasks simultaneously.

Comparison feature
──────────────────
When `gainers_context` is supplied (i.e. the searched ticker is NOT in today's
gainer list), the prompt includes the top-3 gainers and asks the model to
explain how the searched stock differs.  The result is surfaced as
`GainerAnalysis.comparison_to_gainers`.
"""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import (
    FundamentalsData,
    GainerAnalysis,
    NewsItem,
    StockGainer,
    StockPrediction,
)

log = get_logger(__name__)

_DISCLAIMER = (
    "This is AI-generated analysis for educational purposes only. "
    "It is not investment advice under any regulatory framework. "
    "Past AI analysis performance does not guarantee future accuracy. "
    "Always consult a registered financial advisor before making investment decisions."
)

_SYSTEM_PROMPT = """You are a financial analyst who explains why stocks move and predicts 30-day outlooks.
Write clearly for a beginner investor — no jargon without explanation.
Never recommend buying or selling. Only describe what happened and what the data suggests.
Identify related stocks that may benefit from the same catalyst.
If context about today's top gainers is provided, compare the analysed stock against them.
Always respond in valid JSON matching the schema provided."""

# ── Combined response schema (analysis + prediction in one call) ──────────────

_COMBINED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # ─ Analysis ─────────────────────────────────────────────────────────
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
        "analysis_confidence": {"type": "number"},
        "related_beneficiaries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 ticker symbols likely to benefit from the same catalyst",
        },
        "beneficiary_reasoning": {"type": "string"},
        "comparison_to_gainers": {
            "type": "string",
            "description": (
                "How this stock compares to today's top gainers. "
                "Leave empty string if no gainers context was provided."
            ),
        },
        # ─ Prediction ───────────────────────────────────────────────────────
        "outlook": {"type": "string"},
        "predicted_change_pct": {"type": "number"},
        "prediction_confidence": {"type": "number"},
        "time_horizon": {
            "type": "string",
            "enum": ["days", "weeks", "months"],
        },
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
        "why_it_gained", "key_catalysts", "catalyst_type", "sentiment",
        "is_sustained", "sustainability_reason", "analysis_confidence",
        "related_beneficiaries", "beneficiary_reasoning", "comparison_to_gainers",
        "outlook", "predicted_change_pct", "prediction_confidence", "time_horizon",
        "key_risks", "key_tailwinds", "valuation_signal", "growth_signal", "debt_signal",
    ],
}

_MOCK_RESPONSE: dict[str, Any] = {
    # Analysis
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
    "analysis_confidence": 0.78,
    "related_beneficiaries": ["AMD", "SMCI", "AVGO"],
    "beneficiary_reasoning": (
        "AMD and AVGO operate in the same semiconductor supply chain and often follow "
        "NVDA-driven sector rotations. SMCI benefits directly from AI server demand."
    ),
    "comparison_to_gainers": "",
    # Prediction
    "outlook": (
        "Based on strong earnings and raised guidance, this stock has a reasonable chance of "
        "continued momentum over the next few weeks. The earnings beat removes near-term "
        "uncertainty and institutional investors often continue accumulating after such results."
    ),
    "predicted_change_pct": 4.5,
    "prediction_confidence": 0.60,
    "time_horizon": "weeks",
    "key_risks": [
        "Stock already up sharply — good news may be fully priced in",
        "Broader market correction could drag it down regardless of fundamentals",
        "Elevated expectations leave little room for the next earnings miss",
    ],
    "key_tailwinds": [
        "Earnings momentum typically sustains 2-4 weeks post-results",
        "Raised guidance reduces downside risk",
        "Analyst price target upgrades likely to follow",
    ],
    "valuation_signal": "fairly_valued",
    "growth_signal": "strong",
    "debt_signal": "moderate",
}


class GainerAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse_full(
        self,
        ticker: str,
        change_pct: float,
        company_name: str,
        sector: str | None,
        news: list[NewsItem],
        fundamentals: FundamentalsData | None = None,
        gainers_context: list[StockGainer] | None = None,
    ) -> tuple[GainerAnalysis, StockPrediction | None]:
        """
        Single Gemini call that returns both a GainerAnalysis and a StockPrediction.
        ~40-50 % faster than two sequential calls.

        gainers_context: top gainers from today's list — when supplied (i.e. the
        searched ticker is not in the gainer list) the model compares this stock
        against the day's winners.
        """
        if self._mock:
            log.info("gainer_analyst.mock_response", ticker=ticker)
            mock = {**_MOCK_RESPONSE}
            if gainers_context:
                mock["comparison_to_gainers"] = (
                    f"Today's top gainers (e.g. {gainers_context[0].ticker} +{gainers_context[0].change_pct:.1f}%) "
                    f"are led by {gainers_context[0].sector or 'various'} sector momentum. "
                    f"{ticker} has a different catalyst profile — monitor whether "
                    f"sector rotation brings similar attention."
                )
            analysis = GainerAnalysis(
                ticker=ticker,
                why_it_gained=mock["why_it_gained"],
                key_catalysts=mock["key_catalysts"],
                catalyst_type=mock["catalyst_type"],
                sentiment=mock["sentiment"],
                is_sustained=mock["is_sustained"],
                sustainability_reason=mock["sustainability_reason"],
                confidence=mock["analysis_confidence"],
                related_beneficiaries=mock["related_beneficiaries"],
                beneficiary_reasoning=mock["beneficiary_reasoning"],
                comparison_to_gainers=mock["comparison_to_gainers"] or None,
            )
            prediction = StockPrediction(
                ticker=ticker,
                outlook=mock["outlook"],
                predicted_change_pct=mock["predicted_change_pct"],
                confidence=mock["prediction_confidence"],
                time_horizon=mock["time_horizon"],
                key_risks=mock["key_risks"],
                key_tailwinds=mock["key_tailwinds"],
                valuation_signal=mock["valuation_signal"],
                growth_signal=mock["growth_signal"],
                debt_signal=mock["debt_signal"],
                disclaimer=_DISCLAIMER,
            ) if fundamentals is not None else None
            return analysis, prediction

        raw = await self._call_gemini(
            ticker, change_pct, company_name, sector, news, fundamentals, gainers_context
        )
        try:
            analysis = GainerAnalysis(
                ticker=ticker,
                why_it_gained=raw["why_it_gained"],
                key_catalysts=raw["key_catalysts"],
                catalyst_type=raw["catalyst_type"],
                sentiment=raw["sentiment"],
                is_sustained=raw["is_sustained"],
                sustainability_reason=raw["sustainability_reason"],
                confidence=raw["analysis_confidence"],
                related_beneficiaries=raw.get("related_beneficiaries", []),
                beneficiary_reasoning=raw.get("beneficiary_reasoning"),
                comparison_to_gainers=raw.get("comparison_to_gainers") or None,
            )
        except Exception as exc:
            raise AIAgentError(f"Invalid analysis response for {ticker}: {exc}") from exc

        prediction: StockPrediction | None = None
        if fundamentals is not None:
            try:
                prediction = StockPrediction(
                    ticker=ticker,
                    outlook=raw["outlook"],
                    predicted_change_pct=raw["predicted_change_pct"],
                    confidence=raw["prediction_confidence"],
                    time_horizon=raw["time_horizon"],
                    key_risks=raw["key_risks"],
                    key_tailwinds=raw["key_tailwinds"],
                    valuation_signal=raw["valuation_signal"],
                    growth_signal=raw["growth_signal"],
                    debt_signal=raw["debt_signal"],
                    disclaimer=_DISCLAIMER,
                )
            except Exception as exc:
                log.warning("gainer_analyst.prediction_parse_failed", ticker=ticker, error=str(exc))
                # Return analysis without prediction rather than failing entirely

        return analysis, prediction

    # Kept for backward-compat; callers that only want the analysis can use this.
    async def analyse(
        self,
        ticker: str,
        change_pct: float,
        company_name: str,
        sector: str | None,
        news: list[NewsItem],
    ) -> GainerAnalysis:
        analysis, _ = await self.analyse_full(
            ticker=ticker,
            change_pct=change_pct,
            company_name=company_name,
            sector=sector,
            news=news,
        )
        return analysis

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_gemini(
        self,
        ticker: str,
        change_pct: float,
        company_name: str,
        sector: str | None,
        news: list[NewsItem],
        fundamentals: FundamentalsData | None,
        gainers_context: list[StockGainer] | None,
    ) -> dict[str, Any]:
        import asyncio
        import httpx

        headlines = "\n".join(f"- {n.title} ({n.source})" for n in news[:8])
        fund_text = _format_fundamentals(fundamentals) if fundamentals else "No fundamental data available."

        # Build gainers comparison section
        gainers_section = ""
        if gainers_context:
            lines = [
                f"  • {g.ticker} ({g.sector or 'N/A'}): +{g.change_pct:.1f}%  {g.name}"
                for g in gainers_context[:3]
            ]
            gainers_section = (
                "\n\nTODAY'S TOP GAINERS (for comparison — this stock is NOT in the gainer list):\n"
                + "\n".join(lines)
                + "\n\nCompare: explain how the analysed stock's move and catalyst differ from these "
                "top gainers. What does it mean that it didn't make the top-gainer list today? "
                "Populate the `comparison_to_gainers` field with 2-3 sentences."
            )

        prompt = (
            f"Stock: {company_name} ({ticker})\n"
            f"Sector: {sector or 'Unknown'}\n"
            f"Today's move: +{change_pct:.1f}%\n\n"
            f"RECENT NEWS:\n{headlines or 'No news available.'}\n\n"
            f"FUNDAMENTALS:\n{fund_text}"
            + gainers_section
            + "\n\nAnalyse why this stock moved today, whether momentum is likely to continue, "
            "and predict the 30-day outlook. Identify 2-4 related beneficiary tickers."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2500,   # raised from 1500 — combined schema needs ~1800-2200 tokens
                "responseMimeType": "application/json",
                "responseSchema": _COMBINED_SCHEMA,
            },
        }

        token = await asyncio.to_thread(get_cached_token)
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()

        raw_resp = resp.json()

        # Log finish reason so truncation is visible in Cloud Run logs
        finish_reason = (
            raw_resp.get("candidates", [{}])[0].get("finishReason", "UNKNOWN")
        )
        if finish_reason not in ("STOP", "UNKNOWN"):
            log.warning(
                "gainer_analyst.gemini_non_stop_finish",
                ticker=ticker,
                finish_reason=finish_reason,
            )

        try:
            text = raw_resp["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            log.error(
                "gainer_analyst.gemini_unexpected_shape",
                ticker=ticker,
                response_keys=list(raw_resp.keys()),
            )
            raise AIAgentError(f"Unexpected Gemini response shape for {ticker}") from exc

        try:
            parsed = json.loads(text)
            log.info("gainer_analyst.gemini_ok", ticker=ticker, finish_reason=finish_reason)
            return parsed
        except json.JSONDecodeError as exc:
            log.error(
                "gainer_analyst.gemini_invalid_json",
                ticker=ticker,
                finish_reason=finish_reason,
                preview=text[:300],
            )
            raise AIAgentError(f"Gemini returned invalid JSON for {ticker}: {text[:200]}") from exc


def _format_fundamentals(f: FundamentalsData) -> str:
    lines: list[str] = []
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
