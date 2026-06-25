"""
ThesisAnalystAgent — single Gemini call that turns a user's investment belief
into a structured conviction thesis with instruments, confirmers, and signals.

Example input:  "I believe AI will drive massive memory demand"
Example output: ThesisConviction with DRAM ETF / MU / NVDA calls, entry signal,
                thesis confirmers, exit triggers.

The response is cached per (belief, market) pair so repeated searches are instant.
"""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import ThesisConviction, ThesisInstrument, ThesisConfirmer

log = get_logger(__name__)

_DISCLAIMER = (
    "This is AI-generated analysis for educational purposes only. "
    "It is not investment advice under any regulatory framework. "
    "Past AI analysis performance does not guarantee future accuracy. "
    "Always consult a registered financial advisor before making investment decisions."
)

_SYSTEM_PROMPT = """You are a conviction-investing analyst who helps investors turn their beliefs about the world into specific, actionable market instruments.

Your job — in order:
1. Identify the structural theme (not just a sector — a specific multi-year shift with measurable drivers)
2. Score conviction honestly using the framework below
3. Suggest exactly 3 instruments (lower risk / focused / higher risk) that express the thesis
4. Cite real, specific evidence for and against (not generic statements)
5. Define a precise entry timing signal and measurable exit conditions

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — MARKET FOCUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Read the market context provided in the user message.

  US market: Use US-listed tickers (NYSE/NASDAQ). ETF first for lower risk, then sector leader, then leveraged/concentrated bet.

  India market: Use NSE-listed tickers. Follow this instrument hierarchy:
    - Lower risk:  Broad Nifty/sector ETF (e.g. Nifty BeES, Mirae Asset Nifty India Manufacturing ETF, HDFC Nifty 50 ETF)
                   OR large-cap sector leader from NSE (suffix .NS)
    - Focused:     Direct NSE stock that is the most direct beneficiary of the thesis
    - Higher risk: Mid-cap or pure-play NSE stock with highest earnings leverage to the thesis

  India-specific instrument rules:
    - Never suggest ADRs or US-listed stocks for an India thesis
    - Prefer direct NSE stocks over MFs unless the belief is purely macro (e.g. "India infrastructure boom" → L&T, NTPC, IRB Infra)
    - For themes like "India defence indigenisation": HAL, BEL, Mazagon Dock, Data Patterns
    - For themes like "India financialisation of savings": HDFC AMC, Nippon Life India AMC, Angel One
    - For themes like "India EV adoption": Tata Motors, Exide Industries, Sona BLW
    - For themes like "India renewables": NTPC Renewable, Adani Green, Websol Energy
    - Always verify the ticker exists on NSE before using it

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — CONVICTION SCORING (0-100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Score based on EVIDENCE QUALITY, not enthusiasm. Use these anchors:

  90-100  Iron-clad structural shift. Multiple independent data sources confirm.
          Revenue already showing up in earnings. Analyst consensus aligned.
          Example: "AI chip demand" — NVDA/AMD earnings confirmed, hyperscaler capex confirmed,
          HBM pricing confirmed. All three legs of the stool are solid.

  70-89   Strong trend with 2 of 3 confirmation legs in place.
          Revenue growing but guidance/analyst consensus not fully caught up yet.
          Example: "India defence indigenisation" — government orders placed, HAL/BEL revenue growing,
          but delivery timelines uncertain. Thesis is playing out but execution lag remains.

  50-69   Developing thesis. Directionally correct but early-stage.
          1 of 3 legs confirmed. Revenue uplift not yet visible in reported numbers.
          Policy intent clear but private capex not yet responding.
          Example: "India EV adoption" — policy subsidies in place, Tata Motors EV share growing,
          but charging infrastructure and battery localisation are still missing legs.

  30-49   Speculative. The belief is plausible but evidence is thin or contradictory.
          No meaningful revenue impact visible yet. Multiple execution dependencies.

  0-29    Highly speculative or contrary to current data. Flag clearly.

  Scoring rules:
  - Start at 50. Add/subtract based on evidence quality of confirmers.
  - Each "confirmed" data point with specific numbers: +10 to +15
  - Each "watch" signal (directionally right, not yet confirmed): +5
  - Each "risk" signal (active counter-evidence): -10 to -20
  - Cap at 95 — nothing is certain.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — INSTRUMENTS (exactly 3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  lower risk:  Diversified ETF or sector index fund — reduces single-stock risk
               Rationale must name the specific basket it holds
  focused:     Single stock that is the most direct, highest-quality beneficiary
               Rationale must cite a specific metric (revenue %, market share, backlog size)
  higher risk: More concentrated, smaller-cap, or higher-multiple play
               Rationale must explicitly name the risk (valuation, execution, liquidity)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — CONFIRMERS (3-5 items)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each confirmer must be a specific, real data point — not a generic statement.

  GOOD: "NVDA data centre revenue grew 427% YoY in Q2 FY25" (status: confirmed)
  GOOD: "India MoD order book for HAL crossed ₹1.4 lakh crore" (status: confirmed)
  GOOD: "Samsung adding 30% DRAM capacity — potential oversupply in 2026" (status: risk)
  BAD:  "AI is growing fast" (too generic — no number, no timeline)
  BAD:  "Government is supportive" (vague — cite the specific policy/budget line)

  status: "confirmed" = already in reported data / policy gazette / official announcement
          "watch"     = directionally right but not yet in reported numbers
          "risk"      = active counter-evidence that could invalidate the thesis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — ENTRY SIGNAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "strong" = Price has pulled back from recent high + thesis evidence remains intact.
             Give a specific condition: e.g. "Sector ETF is 12% below its 52-week high with no thesis deterioration — strong entry window"
  "fair"   = Thesis well-known to market, stocks trading near fair value.
             Give a specific condition: e.g. "MU trading at 22× forward PE vs 5yr avg of 18× — fair entry, not ideal. A 10-15% pullback on macro fears would improve it."
  "wait"   = Stocks have run significantly ahead of earnings delivery.
             Give a specific condition: e.g. "HAL trading at 45× earnings while delivery slippage risk is high — wait for Q2 results before entering."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 — EXIT TRIGGERS (2-3 items)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each trigger must be specific and measurable — not vague.

  GOOD: "DRAM spot prices fall >15% for 3 consecutive months" (specific, measurable)
  GOOD: "India defence budget allocation drops below 2% of GDP for 2 consecutive years"
  GOOD: "Key focused-stock misses revenue guidance by >15% for 2 consecutive quarters"
  BAD:  "If the theme reverses" (unmeasurable)
  BAD:  "When the stock becomes overvalued" (no threshold)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FINAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Never say "buy" or "sell" — describe what the data shows
- Use real, currently-traded ticker symbols only — verify they exist
- time_horizon: be specific ("2-3 years", "multi-year (5yr+)", "6-12 months") not just "long-term"
- Always respond in valid JSON matching the schema provided"""


_COMBINED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "belief": {"type": "string", "description": "Cleaned-up version of the user's belief"},
        "theme_label": {
            "type": "string",
            "description": "Short uppercase label, 2-4 words, e.g. AI MEMORY DEMAND",
        },
        "conviction_score": {
            "type": "number",
            "description": "0-100 score for how strongly evidence supports the thesis",
        },
        "thesis_summary": {
            "type": "string",
            "description": "1-2 sentence explanation of the structural shift and why it matters",
        },
        "instruments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "name": {"type": "string"},
                    "risk_level": {
                        "type": "string",
                        "enum": ["lower", "focused", "higher"],
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief label, e.g. 'Diversified basket'",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this instrument expresses the thesis",
                    },
                },
                "required": ["ticker", "name", "risk_level", "description", "rationale"],
            },
        },
        "confirmers": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Real-world data point, e.g. 'NVIDIA HBM orders up 40%'",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["confirmed", "watch", "risk"],
                    },
                },
                "required": ["text", "status"],
            },
        },
        "entry_signal": {
            "type": "string",
            "enum": ["strong", "fair", "wait"],
        },
        "entry_explanation": {
            "type": "string",
            "description": "Short explanation of why now is strong / fair / not ideal to enter",
        },
        "exit_triggers": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {"type": "string"},
            "description": "Specific conditions that would invalidate the thesis",
        },
        "time_horizon": {
            "type": "string",
            "description": "Expected duration, e.g. 'multi-year', '1-2 years', '6-12 months'",
        },
    },
    "required": [
        "belief", "theme_label", "conviction_score", "thesis_summary",
        "instruments", "confirmers", "entry_signal", "entry_explanation",
        "exit_triggers", "time_horizon",
    ],
}


_MOCK_RESPONSE: dict[str, Any] = {
    "belief": "AI will drive massive demand for memory chips",
    "theme_label": "AI MEMORY DEMAND",
    "conviction_score": 81.0,
    "thesis_summary": (
        "AI model training and inference require orders of magnitude more memory bandwidth "
        "than traditional workloads, making HBM and DRAM a structural bottleneck. "
        "Data center spend on memory is forecast to grow at 30%+ CAGR through 2027."
    ),
    "instruments": [
        {
            "ticker": "MXU",
            "name": "VanEck Semiconductor ETF",
            "risk_level": "lower",
            "description": "Diversified basket",
            "rationale": (
                "Spreads exposure across DRAM makers, NAND suppliers, and their equipment "
                "vendors so a single-stock miss doesn't sink the thesis."
            ),
        },
        {
            "ticker": "MU",
            "name": "Micron Technology",
            "risk_level": "focused",
            "description": "Pure-play US DRAM",
            "rationale": (
                "Micron is the only US-headquartered DRAM manufacturer and holds #3 "
                "global HBM share. A direct, concentrated bet on the memory cycle thesis."
            ),
        },
        {
            "ticker": "NVDA",
            "name": "NVIDIA Corporation",
            "risk_level": "higher",
            "description": "AI infrastructure leverage",
            "rationale": (
                "Already at a premium valuation, NVDA amplifies memory demand upside "
                "because GPU attach rate drives HBM consumption. Higher multiple = "
                "more volatility, but maximum thesis leverage."
            ),
        },
    ],
    "confirmers": [
        {"text": "NVIDIA H100/H200 GPU backlog extending to late 2025", "status": "confirmed"},
        {"text": "SK Hynix HBM3E capacity sold out through 2025", "status": "confirmed"},
        {"text": "Micron HBM revenue tripled year-over-year in latest quarter", "status": "confirmed"},
        {"text": "Samsung ramping aggressive DRAM capacity — supply risk emerging", "status": "watch"},
        {"text": "China export restrictions may limit NVDA revenue growth", "status": "risk"},
    ],
    "entry_signal": "fair",
    "entry_explanation": (
        "Memory stocks have already re-rated significantly from 2023 lows. "
        "The thesis is well-understood by the market, so upside is more gradual. "
        "A 10-15% pullback on macro fears would be a stronger entry."
    ),
    "exit_triggers": [
        "DRAM spot prices fall >15% for 3 consecutive months (demand destruction)",
        "NVIDIA cuts data center revenue guidance by >20%",
        "China government mandates domestic DRAM procurement",
    ],
    "time_horizon": "multi-year",
}


class ThesisAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse(self, belief: str, market: str = "us") -> ThesisConviction:
        """
        Analyse an investment belief and return a structured conviction thesis.
        """
        if self._mock:
            log.info("thesis_analyst.mock_response", belief=belief[:80])
            return _build_conviction(_MOCK_RESPONSE)

        raw = await self._call_gemini(belief, market)
        try:
            return _build_conviction(raw)
        except Exception as exc:
            raise AIAgentError(f"Invalid thesis response: {exc}") from exc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_gemini(self, belief: str, market: str) -> dict[str, Any]:
        import asyncio
        import httpx

        market_context = (
            "Focus on US-listed stocks and ETFs unless the user's belief specifically mentions another region."
            if market == "us"
            else "Focus on NSE/BSE-listed Indian stocks and relevant ETFs. Use NSE ticker symbols."
        )

        prompt = (
            f"Investment belief: \"{belief}\"\n\n"
            f"Market focus: {market_context}\n\n"
            "Turn this belief into a conviction thesis. "
            "Suggest 3 instruments (one lower-risk, one focused, one higher-risk) "
            "that express this belief. "
            "Assess whether evidence supports the thesis right now. "
            "Give an honest entry timing signal and clear exit conditions."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2000,
                "responseMimeType": "application/json",
                "responseSchema": _COMBINED_SCHEMA,
                # Disable thinking — keeps latency low for structured JSON calls.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        token = await get_token()
        project = self._settings.google_cloud_project
        region = self._settings.google_cloud_region
        model = self._settings.vertex_ai_model_flash
        url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/publishers/google/models/{model}:generateContent"
        )

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                log.error(
                    "thesis_analyst.gemini_http_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                raise AIAgentError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")

        raw_resp = resp.json()

        finish_reason = (
            raw_resp.get("candidates", [{}])[0].get("finishReason", "UNKNOWN")
        )
        if finish_reason not in ("STOP", "UNKNOWN"):
            log.warning(
                "thesis_analyst.gemini_non_stop_finish",
                belief_preview=belief[:60],
                finish_reason=finish_reason,
            )

        try:
            text = raw_resp["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            log.error(
                "thesis_analyst.gemini_unexpected_shape",
                response_keys=list(raw_resp.keys()),
            )
            raise AIAgentError("Unexpected Gemini response shape for thesis") from exc

        try:
            parsed = json.loads(text)
            log.info("thesis_analyst.gemini_ok", finish_reason=finish_reason)
            return parsed
        except json.JSONDecodeError as exc:
            log.error(
                "thesis_analyst.gemini_invalid_json",
                finish_reason=finish_reason,
                preview=text[:300],
            )
            raise AIAgentError(f"Gemini returned invalid JSON for thesis: {text[:200]}") from exc


def _build_conviction(raw: dict[str, Any]) -> ThesisConviction:
    instruments = [
        ThesisInstrument(
            ticker=i["ticker"],
            name=i["name"],
            risk_level=i["risk_level"],
            description=i["description"],
            rationale=i["rationale"],
        )
        for i in raw["instruments"]
    ]
    confirmers = [
        ThesisConfirmer(text=c["text"], status=c["status"])
        for c in raw["confirmers"]
    ]
    return ThesisConviction(
        belief=raw["belief"],
        theme_label=raw["theme_label"].upper(),
        conviction_score=float(raw["conviction_score"]),
        thesis_summary=raw["thesis_summary"],
        instruments=instruments,
        confirmers=confirmers,
        entry_signal=raw["entry_signal"],
        entry_explanation=raw["entry_explanation"],
        exit_triggers=raw["exit_triggers"],
        time_horizon=raw["time_horizon"],
        disclaimer=_DISCLAIMER,
    )
