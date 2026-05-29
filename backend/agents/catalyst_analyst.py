"""
CatalystAnalystAgent — one batch Gemini call that writes plain-English verdicts
for the top moving stocks in the Catalyst Scanner.

Design
──────
• Single call: up to 10 stocks → one Gemini request (JSON structured output).
• Cost: ~$0.0002 per scan (well under $0.001/call).
• Each verdict: 2 sentences — what caused the move, and whether it looks sustained.
• Falls back to a keyword-based default verdict on Gemini failure so the scan
  endpoint never returns empty verdicts.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_cached_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger

log = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a catalyst analyst writing concise plain-English verdicts for retail investors.
For each stock provided, write exactly 2 sentences:
  1. What specific catalyst is driving the move (cite the actual news if given).
  2. Whether the move looks sustained or likely to fade, and the one signal to watch.
Keep each verdict under 55 words total. No jargon. No disclaimers.\
"""

_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "object",
            "description": "Map of ticker symbol → 2-sentence verdict string",
            "additionalProperties": {"type": "string"},
        }
    },
    "required": ["verdicts"],
}

_MOCK_VERDICTS: dict[str, str] = {}  # filled per-call in mock mode


def _default_verdict(ticker: str, change_pct: float, has_catalyst: bool) -> str:
    if has_catalyst:
        return (
            f"{ticker} is surging {change_pct:+.1f}% on a specific news catalyst "
            f"— confirmed by unusual volume. "
            "Watch whether volume sustains above average in the next 2 sessions; "
            "a volume fade signals the move is exhausting."
        )
    return (
        f"{ticker} is up {change_pct:+.1f}% with no clear news catalyst identified — "
        "this may be sector rotation or momentum trading. "
        "Treat this as speculative until a fundamental driver emerges."
    )


class CatalystAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse(
        self,
        movers: list[dict[str, Any]],
        market: str,
    ) -> dict[str, str]:
        """
        Given a list of raw mover dicts (ticker, name, change_pct, volume_ratio,
        headline_catalyst, has_catalyst), return a dict of ticker → verdict string.
        Always returns a complete dict — falls back to keyword defaults on failure.
        """
        if not movers:
            return {}

        if self._mock:
            return {
                m["ticker"]: _default_verdict(
                    m["ticker"],
                    m.get("change_pct", 0.0),
                    bool(m.get("has_catalyst")),
                )
                for m in movers
            }

        try:
            return await self._call_gemini(movers, market)
        except Exception as exc:
            log.warning("catalyst_analyst.gemini_failed_using_defaults", error=str(exc))
            return {
                m["ticker"]: _default_verdict(
                    m["ticker"],
                    m.get("change_pct", 0.0),
                    bool(m.get("has_catalyst")),
                )
                for m in movers
            }

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _call_gemini(
        self, movers: list[dict[str, Any]], market: str
    ) -> dict[str, str]:
        import asyncio

        market_label = "US (NYSE/NASDAQ)" if market == "us" else "Indian (NSE/BSE)"

        lines: list[str] = []
        for i, m in enumerate(movers[:10], 1):
            ticker = m["ticker"]
            name = m.get("name", ticker)
            chg = m.get("change_pct", 0.0)
            vol_ratio = m.get("volume_ratio")
            vol_str = f"{vol_ratio:.1f}× avg volume" if vol_ratio else "volume unknown"
            sector = m.get("sector") or "unknown sector"
            headline = m.get("headline_catalyst")
            has_catalyst = bool(m.get("has_catalyst"))

            line = f"{i}. {ticker} — {name} | {chg:+.1f}% | {vol_str} | {sector}"
            if headline:
                line += f'\n   Catalyst: "{headline}"'
            elif not has_catalyst:
                line += "\n   No specific news catalyst identified"
            lines.append(line)

        prompt = (
            f"Market: {market_label}\n\n"
            f"MOVING STOCKS:\n" + "\n\n".join(lines) + "\n\n"
            "Write a 2-sentence verdict for each stock. Return only the JSON object."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1200,
                "responseMimeType": "application/json",
                "responseSchema": _VERDICT_SCHEMA,
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

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()

        raw = resp.json()
        try:
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)
            verdicts: dict[str, str] = parsed.get("verdicts", {})
            log.info(
                "catalyst_analyst.gemini_ok",
                market=market,
                tickers=len(verdicts),
            )
            # Fill in defaults for any ticker Gemini missed
            for m in movers:
                if m["ticker"] not in verdicts:
                    verdicts[m["ticker"]] = _default_verdict(
                        m["ticker"], m.get("change_pct", 0.0), bool(m.get("has_catalyst"))
                    )
            return verdicts
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            log.error("catalyst_analyst.parse_error", error=str(exc))
            raise AIAgentError(f"Catalyst analyst parse error: {exc}") from exc
