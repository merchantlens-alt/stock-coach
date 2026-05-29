"""
RadarAnalystAgent — reads a batch of financial news headlines and identifies
structural themes that could benefit specific stocks in the next 5-30 days.

Design principles
─────────────────
• Forward-looking: finds stocks that HAVEN'T moved yet, not those that already popped.
• Single Gemini call: 25 news items → up to 5 signals.  Very token-efficient.
• Cost: ~$0.0004 per call × 2 calls/day = $0.0003/day.
• Cache: 12 h per market.  Fresh at market open and midday.

Honest about uncertainty: returns 0 signals when evidence is weak rather than
manufacturing picks from noise.
"""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import NewsItem, RadarSignal, RadarResponse, Market

log = get_logger(__name__)

_SYSTEM_PROMPT = """You are a catalyst radar analyst who reads financial news and identifies
structural themes that could benefit specific stocks in the next 5-30 days.

Your job is NOT to comment on stocks that have already moved. You look for stocks that
HAVEN'T moved yet but are positioned to benefit from an emerging theme.

Rules:
- Only use the provided news headlines — do not rely on prior knowledge about current prices
- Focus on STRUCTURAL narratives, not one-day events: supply chain shifts, regulatory changes,
  technology adoption curves, earnings cycle setups, macro policy moves
- conviction score (0-1): how much evidence in the provided news supports this theme
  (0.8+ = multiple strong confirmers, 0.5-0.79 = developing signal, below 0.5 = too speculative)
- Only return signals with conviction ≥ 0.5
- Return 0 signals if there are no credible structural themes — silence is better than noise
- source_headlines: quote 1-3 actual headline titles from the provided list that support this theme
- tickers: real publicly-traded symbols only; 1-4 tickers per signal
- Always respond in valid JSON matching the schema provided"""

_RADAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "signals": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "theme": {
                        "type": "string",
                        "description": "Short theme name in title case, e.g. 'AI Memory Bandwidth Squeeze'",
                    },
                    "narrative": {
                        "type": "string",
                        "description": "2-3 sentences: what's happening, why it matters, why certain stocks haven't priced it in yet",
                    },
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 4,
                    },
                    "catalyst_type": {
                        "type": "string",
                        "enum": [
                            "earnings", "fda_approval", "acquisition", "partnership",
                            "analyst_upgrade", "macro", "technical", "regulatory", "unknown",
                        ],
                    },
                    "conviction": {
                        "type": "number",
                        "description": "0-1 evidence score based solely on provided news",
                    },
                    "time_frame": {
                        "type": "string",
                        "description": "When this could play out, e.g. '3-5 days', '1-2 weeks', '1 month+'",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "The specific data point or development driving this signal",
                    },
                    "source_headlines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                        "description": "Actual headline text(s) from the provided list that support this theme",
                    },
                },
                "required": [
                    "theme", "narrative", "tickers", "catalyst_type",
                    "conviction", "time_frame", "evidence", "source_headlines",
                ],
            },
        },
        "no_signals_reason": {
            "type": "string",
            "description": "If signals is empty, explain briefly why (e.g. 'No structural themes with sufficient evidence today')",
        },
    },
    "required": ["signals"],
}

_MOCK_RESPONSE: dict[str, Any] = {
    "signals": [
        {
            "theme": "AI Memory Bandwidth Squeeze",
            "narrative": (
                "Multiple reports indicate AI training runs are now memory-bandwidth limited "
                "rather than compute-limited. HBM3E supply is sold out through Q3. Memory "
                "infrastructure stocks outside NVIDIA haven't fully re-rated for this shift."
            ),
            "tickers": ["MU", "LRCX", "AMAT"],
            "catalyst_type": "macro",
            "conviction": 0.82,
            "time_frame": "2-4 weeks",
            "evidence": (
                "Three separate analyst notes this week cite memory bandwidth, not GPU compute, "
                "as the primary bottleneck for large AI model training."
            ),
            "source_headlines": [
                "NVIDIA cites memory bandwidth as key AI bottleneck — Reuters",
                "SK Hynix HBM3E allocation fully committed through Q3 — Bloomberg",
            ],
        },
        {
            "theme": "Pharmaceutical Pricing Tailwind",
            "narrative": (
                "Senate negotiations on drug pricing reform appear stalled after the CBO revised "
                "its savings estimate down 30%. Large-cap pharma with near-term patent cliffs could "
                "see multiple expansion as pricing pressure risk eases for another 12 months."
            ),
            "tickers": ["LLY", "ABBV", "BMY"],
            "catalyst_type": "regulatory",
            "conviction": 0.65,
            "time_frame": "1-2 weeks",
            "evidence": (
                "Congressional Budget Office revised drug pricing savings estimate down 30% in its "
                "latest memo, signalling the legislation's scope is narrowing."
            ),
            "source_headlines": [
                "Drug pricing legislation stalls in Senate — WSJ",
                "CBO cuts drug savings estimate by 30% — Bloomberg",
            ],
        },
        {
            "theme": "Nuclear Power Rerating",
            "narrative": (
                "Hyperscaler energy deals with nuclear operators are accelerating. Two new "
                "corporate PPA announcements this week show the AI data centre buildout is "
                "treating nuclear as a preferred baseload source. Small modular reactor stocks "
                "trade at a fraction of their 2024 peak despite improving fundamentals."
            ),
            "tickers": ["CEG", "VST", "NNE"],
            "catalyst_type": "partnership",
            "conviction": 0.75,
            "time_frame": "1-2 weeks",
            "evidence": (
                "Two major tech companies announced 15-year nuclear PPAs this week; "
                "combined contracted capacity exceeds 2 GW."
            ),
            "source_headlines": [
                "Microsoft, Google sign nuclear power deals for AI data centres — FT",
                "Nuclear power emerges as preferred AI energy source — Reuters",
            ],
        },
    ],
    "no_signals_reason": "",
}


class RadarAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def scan(self, news: list[NewsItem], market: Market) -> tuple[list[RadarSignal], str | None]:
        """
        Analyse a batch of market news and return (signals, no_signals_reason).
        Returns ([], reason_string) when evidence is insufficient.
        """
        if self._mock:
            log.info("radar_analyst.mock_response", market=market, news_count=len(news))
            signals = [
                RadarSignal(
                    theme=s["theme"],
                    narrative=s["narrative"],
                    tickers=s["tickers"],
                    catalyst_type=s["catalyst_type"],
                    conviction=s["conviction"],
                    time_frame=s["time_frame"],
                    evidence=s["evidence"],
                    source_headlines=s["source_headlines"],
                )
                for s in _MOCK_RESPONSE["signals"]
            ]
            return signals, None

        raw = await self._call_gemini(news, market)
        signals: list[RadarSignal] = []
        for item in raw.get("signals", []):
            try:
                signals.append(RadarSignal(
                    theme=item["theme"],
                    narrative=item["narrative"],
                    tickers=item["tickers"],
                    catalyst_type=item["catalyst_type"],
                    conviction=float(item["conviction"]),
                    time_frame=item["time_frame"],
                    evidence=item["evidence"],
                    source_headlines=item.get("source_headlines", []),
                ))
            except Exception as exc:
                log.warning("radar_analyst.signal_parse_failed", error=str(exc), item=item)
        no_reason = raw.get("no_signals_reason") or None
        return signals, no_reason

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(self, news: list[NewsItem], market: str) -> dict[str, Any]:
        import asyncio
        import httpx

        # Format news as a numbered list — concise to keep input tokens low
        lines: list[str] = []
        for i, item in enumerate(news[:25], 1):
            date_str = item.published_at.strftime("%b %d") if item.published_at else "recent"
            summary_part = f"\n   Summary: {item.summary[:120]}" if item.summary else ""
            lines.append(f"{i}. [{date_str}] {item.title} — {item.source}{summary_part}")
        news_block = "\n".join(lines)

        market_label = "US (NYSE/NASDAQ)" if market == "us" else "Indian (NSE/BSE)"
        prompt = (
            f"Market: {market_label}\n\n"
            f"TODAY'S FINANCIAL NEWS ({len(lines)} items):\n{news_block}\n\n"
            "Identify up to 5 structural catalyst themes from this news that could benefit "
            "specific stocks in the next 5-30 days. Focus on stocks that HAVEN'T moved yet. "
            "Return 0 signals if evidence is weak — do not manufacture picks."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1800,
                "responseMimeType": "application/json",
                "responseSchema": _RADAR_SCHEMA,
                "thinkingConfig": {"thinkingBudget": 0},  # disable thinking — JSON extraction
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

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()

        raw_resp = resp.json()

        finish_reason = raw_resp.get("candidates", [{}])[0].get("finishReason", "UNKNOWN")
        if finish_reason not in ("STOP", "UNKNOWN"):
            log.warning("radar_analyst.gemini_non_stop_finish", finish_reason=finish_reason)

        try:
            text = raw_resp["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            log.error("radar_analyst.gemini_unexpected_shape", response_keys=list(raw_resp.keys()))
            raise AIAgentError("Unexpected Gemini response shape for radar") from exc

        try:
            parsed = json.loads(text)
            log.info("radar_analyst.gemini_ok", market=market, finish_reason=finish_reason,
                     signal_count=len(parsed.get("signals", [])))
            return parsed
        except json.JSONDecodeError as exc:
            log.error("radar_analyst.gemini_invalid_json", preview=text[:300])
            raise AIAgentError(f"Gemini returned invalid JSON for radar: {text[:200]}") from exc
