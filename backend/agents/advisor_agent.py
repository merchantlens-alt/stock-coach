"""
AdvisorAgent — intersects the investor's profile (Bucket 1) with an asset's
metrics (Bucket 2) and produces a structured Buy / Pass / Conditional verdict.

This is the core personalisation layer: the same asset can be a Buy for one
investor and a Pass for another based on horizon, risk capacity, existing
allocation, and tax situation.
"""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import AdvisorRecommendation, InvestorProfile

log = get_logger(__name__)

_DISCLAIMER = (
    "This is AI-generated analysis for educational purposes only. "
    "It is not investment advice. Always consult a registered financial advisor."
)

_SYSTEM_PROMPT = """You are a wealth advisor who evaluates whether a specific investment
is right for a specific investor. You receive:
  1. The investor's profile (horizon, risk tolerance/capacity, existing allocation, goal, tax)
  2. The asset's key metrics (either a stock or a fund)

Your job is to reason through four dimensions and produce a structured verdict:
  A. Horizon fit   — does the investor's timeline match the asset's risk profile?
  B. Risk fit      — does the asset's volatility match tolerance AND financial capacity?
  C. Allocation fit — does adding this fill a gap or add dangerous concentration?
  D. Valuation/quality — is there a margin of safety and sound fundamentals?

Rules:
- Be specific: reference the investor's actual numbers (horizon_years, existing allocation %)
- A stellar asset at the wrong time = PASS
- An okay asset that fills a real gap = CONDITIONAL or BUY
- verdict must be "buy", "pass", or "conditional"
- confidence must be "high", "medium", or "low"
- investor_match_score: 0-100 (100 = perfect fit across all four dimensions)
- reasons_for: 2-4 specific bullets (reference actual metrics)
- reasons_against: 1-3 specific bullets
- suggested_sizing: e.g. "5-8% of investable surplus" or null if PASS
- caveats: practical notes (wrapper, tax, alternative vehicle) or null
- summary: 1-2 sentence verdict that a non-expert can act on
- Always respond in valid JSON matching the schema"""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "verdict", "confidence", "investor_match_score",
        "horizon_fit", "risk_fit", "allocation_fit",
        "reasons_for", "reasons_against", "summary",
    ],
    "properties": {
        "verdict":               {"type": "string", "enum": ["buy", "pass", "conditional"]},
        "confidence":            {"type": "string", "enum": ["high", "medium", "low"]},
        "investor_match_score":  {"type": "number"},
        "horizon_fit":           {"type": "string"},
        "risk_fit":              {"type": "string"},
        "allocation_fit":        {"type": "string"},
        "reasons_for":           {"type": "array", "items": {"type": "string"}},
        "reasons_against":       {"type": "array", "items": {"type": "string"}},
        "suggested_sizing":      {"type": ["string", "null"]},
        "caveats":               {"type": ["string", "null"]},
        "summary":               {"type": "string"},
    },
}


def _mock_recommendation(profile: InvestorProfile, asset_type: str) -> AdvisorRecommendation:
    goal_label = profile.primary_goal.replace("_", " ").title()
    alloc_str = ", ".join(
        f"{a.asset_class} {a.percentage:.0f}%" for a in profile.existing_allocation
    ) or "no existing allocation recorded"
    return AdvisorRecommendation(
        verdict="conditional",
        confidence="medium",
        investor_match_score=65.0,
        horizon_fit=(
            f"With a {profile.horizon_years}-year horizon, the asset has time to compound "
            "through market cycles."
        ),
        risk_fit=(
            f"Your {profile.risk_tolerance} tolerance and {profile.risk_capacity} capacity "
            f"({profile.emergency_fund_months} months emergency fund) can support this asset's "
            "typical volatility profile."
        ),
        allocation_fit=(
            f"Current allocation: {alloc_str}. "
            "Adding this asset may fill a diversification gap."
        ),
        reasons_for=[
            "Asset fits your stated investment horizon",
            "Risk profile broadly aligned with your capacity",
            "Potential to diversify existing allocation",
        ],
        reasons_against=[
            "Full personalised evaluation requires live AI (mock mode active)",
        ],
        suggested_sizing="5-8% of investable surplus",
        caveats="Run with MOCK_AI=false for a full personalised evaluation.",
        summary=(
            f"Based on your {profile.horizon_years}-year horizon and {goal_label} goal, "
            "this asset is a conditional match. Enable live AI for detailed reasoning."
        ),
        disclaimer=_DISCLAIMER,
    )


class AdvisorAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        model = settings.vertex_ai_model_flash
        region = settings.google_cloud_region
        project = settings.google_cloud_project
        self._endpoint = (
            f"https://{region}-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/{region}/"
            f"publishers/google/models/{model}:generateContent"
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(self, user_prompt: str) -> dict[str, Any]:
        import httpx
        token = await get_token()
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _SCHEMA,
                "temperature": 0.3,
                "maxOutputTokens": 1024,
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                log.error(
                    "advisor_agent.gemini_http_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            resp.raise_for_status()
            return resp.json()

    async def evaluate(
        self,
        profile: InvestorProfile,
        asset_type: str,
        ticker: str,
        name: str | None,
        context: dict,
    ) -> AdvisorRecommendation:
        if self._settings.mock_ai:
            log.info("advisor_agent.mock", ticker=ticker, asset_type=asset_type)
            return _mock_recommendation(profile, asset_type)

        alloc_str = json.dumps(
            [{"asset_class": a.asset_class, "pct": a.percentage} for a in profile.existing_allocation],
            indent=2,
        )

        user_prompt = f"""
INVESTOR PROFILE:
- Investment horizon: {profile.horizon_years} years ({profile.horizon_label})
- Risk tolerance (psychological): {profile.risk_tolerance}
- Risk capacity (financial): {profile.risk_capacity}
- Emergency fund: {profile.emergency_fund_months} months
- Primary goal: {profile.primary_goal}
- Tax residency: {profile.tax_residency}
- Existing portfolio allocation:
{alloc_str}
{"- Monthly surplus: " + str(profile.monthly_surplus) if profile.monthly_surplus else ""}

ASSET BEING EVALUATED:
- Type: {asset_type}
- Ticker / Code: {ticker}
{"- Name: " + name if name else ""}
- Key metrics:
{json.dumps(context, indent=2, default=str)}

Evaluate whether this {asset_type} is a Buy, Pass, or Conditional buy FOR THIS SPECIFIC INVESTOR.
Reason through: horizon fit, risk fit, allocation fit, and valuation/quality.
Produce the structured JSON verdict.
"""

        try:
            raw = await self._call_gemini(user_prompt)
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
            return AdvisorRecommendation(
                verdict=data["verdict"],
                confidence=data["confidence"],
                investor_match_score=float(data.get("investor_match_score", 50)),
                horizon_fit=data.get("horizon_fit", ""),
                risk_fit=data.get("risk_fit", ""),
                allocation_fit=data.get("allocation_fit", ""),
                reasons_for=data.get("reasons_for", []),
                reasons_against=data.get("reasons_against", []),
                suggested_sizing=data.get("suggested_sizing"),
                caveats=data.get("caveats"),
                summary=data.get("summary", ""),
                disclaimer=_DISCLAIMER,
            )
        except Exception as exc:
            log.error("advisor_agent.ai_failed", ticker=ticker, error=str(exc))
            raise AIAgentError(f"Advisor evaluation failed: {exc}") from exc
