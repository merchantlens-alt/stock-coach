"""
PortfolioXrayAgent — turns a PRE-COMPUTED portfolio analysis into a plain-English
advisor summary. Data-first: the agent only summarises numbers it's given; it
never invents holdings or figures.

Falls back to a deterministic heuristic narrative on any Gemini failure (and in
mock mode), so the X-ray endpoint always returns a readable assessment.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger

log = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a seasoned wealth advisor summarising a PRE-COMPUTED portfolio analysis for a retail investor.

Strict rule: use ONLY the numbers and facts provided below. Never invent holdings, sectors, or figures.

Write 4-6 sentences, plain English, direct, no disclaimers:
1. How well-diversified / positioned the portfolio is for the investor's stated risk goal.
2. The most important gap or concentration to address.
3. One or two concrete next actions.
If India funds are present, note that India sector/company look-through isn't available (only allocation), so don't claim India sector detail.\
"""


def _fmt_slices(slices: list[Any]) -> str:
    return ", ".join(f"{s.label} {s.pct:.0f}%" for s in slices) or "n/a"


def _fmt_sectors(slices: list[Any]) -> str:
    return ", ".join(f"{s.sector} {s.pct:.0f}%" for s in slices) or "n/a"


def _fmt_companies(c: list[Any]) -> str:
    return ", ".join(f"{x.name.split(' ')[0]} {x.pct:.1f}%" for x in c) or "n/a"


def _heuristic(*, risk, geography, caps, sectors, companies, redundancies, gaps,
               flagged, sector_coverage, has_india) -> str:
    parts: list[str] = []
    if geography:
        parts.append(f"Your portfolio is {_fmt_slices(geography)} by geography.")
    if caps:
        parts.append(f"By cap it tilts {_fmt_slices(caps[:3])}.")
    if sector_coverage > 0 and sectors:
        parts.append(f"The US sleeve ({sector_coverage*100:.0f}% of the book with look-through) leans {_fmt_sectors(sectors[:3])}"
                     + (f", led by {companies[0].name.split(' ')[0]}." if companies else "."))
    if has_india:
        parts.append("India funds are analysed at the allocation level (holdings look-through isn't available there).")
    if redundancies:
        parts.append("Overlap to clean up: " + redundancies[0])
    if flagged:
        parts.append(f"Watch these: {', '.join(flagged[:3])}.")
    if gaps:
        parts.append(f"To improve for your {risk} goal: " + " ".join(gaps[:2]))
    return " ".join(parts) or "Add a few funds to see your allocation, sector exposure and gaps."


class PortfolioXrayAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def summarise(self, **data: Any) -> str:
        if self._mock:
            return _heuristic(**data)
        try:
            return await self._call_gemini(**data)
        except Exception as exc:
            log.warning("xray_agent.gemini_failed_using_heuristic", error=str(exc))
            return _heuristic(**data)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _call_gemini(self, **data: Any) -> str:
        prompt = (
            f"Risk goal: {data['risk']}\n"
            f"Geography: {_fmt_slices(data['geography'])}\n"
            f"Cap allocation: {_fmt_slices(data['caps'])}\n"
            f"US sector look-through ({data['sector_coverage']*100:.0f}% of portfolio): {_fmt_sectors(data['sectors'])}\n"
            f"Top US companies: {_fmt_companies(data['companies'])}\n"
            f"Redundancies: {'; '.join(data['redundancies']) or 'none'}\n"
            f"Quality flags: {', '.join(data['flagged']) or 'none'}\n"
            f"Computed gaps: {' '.join(data['gaps']) or 'none'}\n"
            f"India funds present: {data['has_india']}\n\n"
            "Write the 4-6 sentence summary."
        )
        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
        }
        token = await get_token()
        s = self._settings
        url = (
            f"https://{s.google_cloud_region}-aiplatform.googleapis.com/v1/projects/"
            f"{s.google_cloud_project}/locations/{s.google_cloud_region}/publishers/google/"
            f"models/{s.vertex_ai_model_flash}:generateContent"
        )
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                log.error("xray_agent.gemini_http_error", status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()
        try:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise AIAgentError(f"X-ray agent parse error: {exc}") from exc
