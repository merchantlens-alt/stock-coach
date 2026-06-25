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

_SYSTEM_PROMPT = """You are a wealth advisor who evaluates whether a specific investment is right for a specific investor.

You receive the investor's full profile and the asset's key metrics. Reason through all four dimensions below — in order — before reaching a verdict. Every dimension has pass/fail criteria. One hard fail = PASS verdict (regardless of other scores).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION A — HORIZON FIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Match the investor's horizon_years against the asset's minimum holding period:

  Asset type             Minimum horizon for BUY   Conditional range   Hard PASS below
  ─────────────────────  ─────────────────────────  ──────────────────  ───────────────
  Large-cap equity       5 years                   3-5 years           < 3 years
  Mid/small-cap equity   7 years                   5-7 years           < 5 years
  Equity MFs (flexi)     5 years                   3-5 years           < 3 years
  Debt MFs (short)       1 year                    6m-1yr              < 6 months
  Debt MFs (long/gilt)   3 years                   2-3 years           < 2 years
  Gold (ETF)             3 years                   1-3 years           < 1 year
  SGB                    8 years (maturity benefit) 5-8 years (exit)   < 5 years
  REIT                   5 years                   3-5 years           < 3 years
  US ETF (India-domiciled) 5 years                 3-5 years           < 3 years

If horizon falls in the hard PASS range → verdict = "pass", confidence = "high".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION B — RISK FIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluate BOTH tolerance (psychological) AND capacity (financial). The binding constraint is whichever is lower.

  Capacity flags (financial hard limits):
  - Emergency fund < 3 months → reduce equity allocation, never BUY aggressive assets
  - Emergency fund 3-6 months → CONDITIONAL on equity; conservative/debt preferred
  - Emergency fund >= 6 months → capacity is healthy, proceed on tolerance

  Tolerance vs asset volatility:
  - Conservative investor + mid/small cap equity → PASS
  - Conservative investor + large-cap equity → CONDITIONAL at most (5-8% sizing max)
  - Moderate investor + large-cap equity or diversified MF → BUY eligible
  - Moderate investor + mid/small cap → CONDITIONAL (horizon must be 7yr+)
  - Aggressive investor + any equity → BUY eligible if horizon fits
  - Any investor + leverage or crypto → PASS (outside scope)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION C — ALLOCATION FIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Check existing portfolio for concentration and gaps:

  Concentration hard limits (trigger PASS or CONDITIONAL):
  - Single stock already > 15% of portfolio → adding same stock = PASS
  - Single sector already > 40% of portfolio → adding same sector = CONDITIONAL at best
  - Total equity already >= target ceiling for risk profile:
      Conservative: 35% equity ceiling
      Moderate: 65% equity ceiling
      Aggressive: 85% equity ceiling
    → Adding more equity beyond ceiling = CONDITIONAL (only if adding diversification)

  Gap identification (supports BUY or CONDITIONAL):
  - 0% Gold in portfolio → Gold = gap, supports BUY
  - 0% Debt in portfolio for moderate/conservative → Debt = gap, supports BUY
  - 0% US equity for India resident → US ETF = gap, supports CONDITIONAL
  - Existing allocation already covers this asset class well → "fills no gap", reduces score

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIMENSION D — VALUATION / QUALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use the provided metrics (PE, revenue growth, debt/equity, ROE, analyst rating, expense ratio):

  STOCKS — quality signals:
  - Revenue growth YoY > 15% + profit margin expanding = strong quality signal
  - Revenue growth YoY < 0% + earnings declining = weak quality, reduce score
  - Debt/equity > 3.0 for cyclical sector = fragile balance sheet, flag as risk
  - Debt/equity > 1.5 for financial sector = structural concern
  - ROE > 15% = capital-efficient business (positive)
  - ROE < 8% = poor capital allocation (negative)
  - PE ratio: compare to sector — >2× sector average = expensive, flag it
  - Analyst consensus BUY + price below analyst target = margin of safety
  - Analyst consensus SELL = significant headwind, justify any BUY verdict carefully

  MUTUAL FUNDS / ETFs:
  - Expense ratio > 1.5% (active fund) = value drag, flag it
  - Expense ratio > 0.5% (index/ETF) = expensive, flag it
  - Tracking error > 1% (for index funds/ETFs) = poor replication, flag it
  - 3yr/5yr alpha vs benchmark > 0 consistently = manager skill
  - AUM < ₹500Cr India MF = liquidity risk

  No fundamental data available → lower confidence, flag explicitly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERDICT CALIBRATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "buy"         → Fits on ALL four dimensions. No hard fails. Investor_match_score 75-100.
  "conditional" → 1-2 dimensions are borderline but not hard fails. Score 45-74.
                  Must state the specific condition to upgrade to BUY (e.g. "wait for 3-month pullback").
  "pass"        → Any dimension is a hard fail (especially horizon or risk capacity).
                  Score 0-44. Do NOT recommend sizing.

  confidence:
  - "high"   → Clear verdict, no ambiguity across all four dimensions
  - "medium" → 1-2 dimensions are borderline or data is incomplete
  - "low"    → Multiple dimensions uncertain or insufficient data provided

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Reference the investor's ACTUAL numbers in every dimension field (horizon_years, emergency_fund_months, existing %)
- reasons_for: 2-4 bullets, each citing a specific metric or threshold passed
- reasons_against: 1-3 bullets, each citing a specific risk or threshold missed
- suggested_sizing: give a % of investable surplus (e.g. "5-8%") — null only for PASS verdict
- caveats: practical notes — tax wrapper (direct vs regular plan), India vs LRS route, liquidity lock-in, or null
- summary: 1-2 sentences a non-expert can act on, written in plain English
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
