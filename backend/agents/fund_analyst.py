"""
FundAnalystAgent — one batch Gemini call that writes a plain-English entry
verdict for each scanned mutual fund.

Design (mirrors CatalystAnalystAgent)
─────────────────────────────────────
• Single call: up to ~20 funds → one Gemini request (JSON structured output).
• Each verdict: 1-2 sentences answering "should I enter this now, and why?"
  grounded in the NAV-derived metrics we pass in.
• Falls back to the heuristic reason (services.fund_metrics.build_entry_reason)
  on any Gemini failure, so the scan endpoint never returns empty reasoning.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from services.fund_metrics import build_entry_reason

log = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a seasoned wealth advisor writing concise entry verdicts on India mutual funds.

For each fund you are given: its category, how it ranks WITHIN that category (rank N of M peers), NAV-derived metrics (rolling returns, 3yr/5yr/since-inception CAGR, Sharpe, max drawdown), its active return vs the category's passive benchmark, a track-record tier (established/emerging/new), and computed flags.

Rules for your verdict (1-2 sentences, under 45 words, no disclaimers):
- Judge funds RELATIVE TO THEIR CATEGORY peers, never absolute — a 12% CAGR is poor for small-cap, good for large-cap.
- If flagged CLOSET INDEX: say it hugs its benchmark and isn't worth the active fee.
- If flagged DECAYING: say its recent return has faded below its long-term CAGR (saturation / style-drift) — past returns flatter the present.
- If flagged DISCOVERY: a young fund already beating peers — promising, but smaller track record, position as a satellite not a core.
- Otherwise cite the single metric (category rank, Sharpe, or active return) that drives enter / hold / avoid.\
"""

_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "object",
            "description": "Map of scheme_code → 1-2 sentence entry verdict string",
            "additionalProperties": {"type": "string"},
        }
    },
    "required": ["verdicts"],
}


def _metrics_of(fund: Any) -> dict[str, Any]:
    """Pull the metric subset from a FundScheme for the heuristic fallback."""
    return {
        "returns_1m":           fund.returns_1m,
        "returns_3m":           fund.returns_3m,
        "returns_6m":           fund.returns_6m,
        "returns_1y":           fund.returns_1y,
        "returns_3y_cagr":      fund.returns_3y_cagr,
        "returns_5y_cagr":      fund.returns_5y_cagr,
        "since_inception_cagr": fund.since_inception_cagr,
        "volatility":           fund.volatility,
        "sharpe":               fund.sharpe,
        "max_drawdown":         fund.max_drawdown,
        "decay_decel":          None,  # not carried on the schema; reason uses flags
    }


def _fallback_reason(fund: Any) -> str:
    """Heuristic reasoning identical to the cold-scan default."""
    return build_entry_reason(
        category=fund.category,
        signal=fund.entry_signal,
        track_record=fund.track_record,
        m=_metrics_of(fund),
        active_return=fund.active_return_3y,
        is_closet=fund.is_closet_index,
        is_decaying=fund.is_decaying,
        is_discovery=fund.is_discovery,
    )


class FundAnalystAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def analyse(self, funds: list[Any]) -> dict[str, str]:
        """
        Given a list of FundScheme objects, return {scheme_code → verdict}.
        Always returns a complete dict — falls back to heuristic reasons on failure.
        """
        if not funds:
            return {}

        if self._mock:
            return {f.scheme_code: _fallback_reason(f) for f in funds}

        try:
            return await self._call_gemini(funds)
        except Exception as exc:
            log.warning("fund_analyst.gemini_failed_using_defaults", error=str(exc))
            return {f.scheme_code: _fallback_reason(f) for f in funds}

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
    async def _call_gemini(self, funds: list[Any]) -> dict[str, str]:
        lines: list[str] = []
        for i, f in enumerate(funds[:25], 1):
            flags = []
            if f.is_closet_index: flags.append("CLOSET_INDEX")
            if f.is_decaying:     flags.append("DECAYING")
            if f.is_discovery:    flags.append("DISCOVERY")
            rank = f"rank {f.category_rank}/{f.category_size}" if f.category_rank else "rank n/a"
            lines.append(
                f"{i}. [{f.scheme_code}] {f.name} ({f.category or 'n/a'}, {f.track_record}) | "
                f"{rank} score={f.fund_score:.0f} signal={f.entry_signal} | "
                f"3m={_fmt(f.returns_3m)} 1y={_fmt(f.returns_1y)} 3yCAGR={_fmt(f.returns_3y_cagr)} "
                f"siCAGR={_fmt(f.since_inception_cagr)} | Sharpe={_fmt(f.sharpe, pct=False)} "
                f"maxDD={_fmt(f.max_drawdown)} activeVsBench={_fmt(f.active_return_3y)} | "
                f"flags={','.join(flags) or 'none'}"
            )

        prompt = (
            "FUNDS (metrics are %, Sharpe is a ratio, activeVsBench is pp vs passive benchmark):\n"
            + "\n".join(lines)
            + "\n\nWrite a 1-2 sentence entry verdict for each fund keyed by its scheme_code, "
            "judging each relative to its category peers. Return only the JSON object."
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1500,
                "responseMimeType": "application/json",
                "responseSchema": _VERDICT_SCHEMA,
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

        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                log.error(
                    "fund_analyst.gemini_http_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            resp.raise_for_status()

        raw = resp.json()
        try:
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            parsed: dict[str, Any] = json.loads(text)
            verdicts: dict[str, str] = parsed.get("verdicts", {})
            log.info("fund_analyst.gemini_ok", funds=len(verdicts))
            # Fill in heuristic defaults for any fund Gemini missed.
            for f in funds:
                if f.scheme_code not in verdicts:
                    verdicts[f.scheme_code] = _fallback_reason(f)
            return verdicts
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            log.error("fund_analyst.parse_error", error=str(exc))
            raise AIAgentError(f"Fund analyst parse error: {exc}") from exc


def _fmt(v: Any, pct: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f}%" if pct else f"{v:.2f}"
