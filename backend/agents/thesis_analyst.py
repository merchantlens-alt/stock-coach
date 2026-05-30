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

from core.auth import get_cached_token
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

_SYSTEM_PROMPT = """You are a conviction-investing analyst who helps beginner investors
turn their beliefs about the world into specific stock market instruments.

Your job:
1. Identify the structural theme behind the user's belief
2. Suggest 3 instruments (lower risk / focused / higher risk) that express the thesis
3. Find real evidence that the thesis is or isn't playing out
4. Give an honest entry timing signal
5. Define clear exit conditions

Rules:
- Use real, publicly traded ticker symbols that actually exist
- Focus on US stocks unless the user specifies India/another market
- Never say "buy" or "sell" — describe what the data shows
- Conviction score: 0-100 based on how much evidence supports the thesis
  (80+ = strong structural trend, 50-79 = developing, below 50 = speculative)
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
