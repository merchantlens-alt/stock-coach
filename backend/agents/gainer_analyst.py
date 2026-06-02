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

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import (
    FundamentalsData,
    GainerAnalysis,
    NewsItem,
    StockGainer,
    StockPrediction,
    TechnicalSignals,
)

log = get_logger(__name__)

_DISCLAIMER = (
    "This is AI-generated analysis for educational purposes only. "
    "It is not investment advice under any regulatory framework. "
    "Past AI analysis performance does not guarantee future accuracy. "
    "Always consult a registered financial advisor before making investment decisions."
)

_SYSTEM_PROMPT = """You are a discretionary financial analyst producing 30-day price predictions.
Write clearly for a beginner investor — no jargon without explanation.
Never recommend buying or selling. Only describe what the data shows.
Identify related stocks that may benefit from the same catalyst.

════════════════════════════════════════════════════
CORE PRINCIPLE: TODAY'S PRICE MOVE ≠ 30-DAY DIRECTION
════════════════════════════════════════════════════

The 30-day outlook must be driven by FUNDAMENTALS + EARNINGS QUALITY + CATALYST TYPE.
Today's price direction is just the starting context — NOT the prediction signal.

  ✓ Strong fundamentals + stock FELL today  → often POSITIVE 30d (market overreacted)
  ✓ Weak fundamentals  + stock GAINED today → often NEGATIVE 30d (speculative, will fade)

  ✗ NEVER: "fell today → predict further decline" (unless fundamentals confirm deterioration)
  ✗ NEVER: "gained today → predict further gains" (unless fundamentals support it)

════════════════════════════════════════════════════
STEP 1 — CLASSIFY TODAY'S MOVE (before predicting anything)
════════════════════════════════════════════════════

Classify the move into one of three categories:

  Category A — Real fundamental shift (business value changed today):
    Earnings beat/miss with guidance change, FDA approval/rejection, major contract win/loss,
    acquisition announced, material guidance cut → this changes intrinsic value.
    → Use this as the 30-day directional anchor.

  Category B — Market/sector noise (business unchanged):
    Macro selloff, rate fears, index rebalancing, sector rotation, profit-taking,
    broader market panic → company fundamentals did NOT change.
    → A Category B DECLINE in a strong-fundamental stock = recovery likely. Set POSITIVE 30d.
    → A Category B GAIN in a weak-fundamental stock = temporary. Set NEGATIVE 30d.

  Category C — Speculative/momentum (no news, thin float):
    Social media chatter, short squeeze, options gamma, rumour, unusual volume with no news.
    → Temporary. Fundamentals set the 30-day direction, not today's move.

════════════════════════════════════════════════════
STEP 2 — ESTABLISH FUNDAMENTAL QUALITY (primary 30-day direction signal)
════════════════════════════════════════════════════

Use FUNDAMENTALS + QUARTERLY EARNINGS together:

  BULLISH signals — positive 30d bias regardless of today's direction:
    • Strong revenue growth + expanding margins + positive earnings trend
    • Earnings inflecting from loss to profit YoY = early re-rating, strongest 30d signal
    • Raised guidance after earnings beat = institutional re-valuation underway
    • Analyst consensus BUY + stock declined = discounted entry, likely recovery
    • RSI <35 + strong fundamentals = oversold, mean reversion very likely → +4–8%

  BEARISH signals — negative 30d bias even if stock gained today:
    • Earnings declining + margins compressing = double squeeze, reversal probable
    • Speculative surge with no real catalyst + weak fundamentals = fade in days
    • High debt + falling revenue = fragile business, next headwind accelerates decline
    • RSI >75 after speculative surge with no real catalyst = likely -5 to -10% pullback

════════════════════════════════════════════════════
STEP 3 — CONFIRM WITH THE CATALYST
════════════════════════════════════════════════════

Does today's news confirm a real business change (Category A) or is it noise (B/C)?
  • Earnings beat / FDA approval / major contract = real catalyst, sustains weeks
  • Analyst upgrade / options activity = momentum-driven, fades faster
  • No identifiable news = speculative; lower confidence, flag in key_risks

════════════════════════════════════════════════════
STEP 4 — USE TECHNICALS TO SIZE AND TIME THE MOVE
════════════════════════════════════════════════════

Technicals REFINE the magnitude and timing — they do NOT set direction.
  • RSI <35 (oversold): expect +3–6% bounce regardless of today's direction
  • RSI >75 (overbought): expect -3–5% consolidation regardless of today's direction
  • Golden cross + volume spike >2×avg: institutional confirmation → raise magnitude +1–3%
  • Price >10% above SMA20: extended → reduce predicted_change_pct by 2–4%
  • MACD bullish cross: momentum building → good timing for next leg

════════════════════════════════════════════════════
STEP 5 — ADJUST FOR GROWTH TRIGGERS (if provided)
════════════════════════════════════════════════════
  • HIGH conviction trigger: +2–5% to predicted_change_pct, +0.05–0.10 to confidence
  • MEDIUM conviction trigger: add to key_tailwinds, +0.03 to confidence
  • OPTIONALITY trigger: add to key_tailwinds only

════════════════════════════════════════════════════
OUTPUT RULES
════════════════════════════════════════════════════
- predicted_change_pct: range -25% to +25%. CALIBRATE TO FUNDAMENTALS, NOT TODAY'S DIRECTION.
    A declined stock with strong fundamentals: USUALLY positive (e.g. +3% to +12%)
    A gained stock with weak fundamentals: USUALLY negative (e.g. -5% to -15%)
- prediction_confidence: 0.0–1.0
    >0.75 = fundamentals strong + catalyst confirmed + technicals aligned (all three agree)
    0.55–0.74 = one or two signals missing or mixed
    <0.55 = conflicting signals — state the conflict clearly in the outlook
- why_it_moved: plain-English explanation of what caused TODAY'S move.
    For declines: use "fell/dropped/declined/slid" — never "gained" for a falling stock.
    For gains: use "surged/rose/gained/climbed".
- key_risks: at least one fundamental risk AND one technical risk
- key_tailwinds: catalyst, earnings trend, any HIGH/MEDIUM growth triggers

ANTI-BIAS CHECKLIST — run this before outputting:
  □ Did I give negative predicted_change_pct ONLY because the stock fell today?
    If yes → re-check fundamentals. Strong fundamentals = recovery probable = positive pct.
  □ Did I give positive predicted_change_pct ONLY because the stock gained today?
    If yes → re-check fundamentals. Weak/speculative = fade probable = negative pct.
  □ Is my outlook consistent with the fundamental quality, not the price momentum?

Always respond in valid JSON matching the schema provided."""

# ── Combined response schema (analysis + prediction in one call) ──────────────

_COMBINED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # ─ Analysis ─────────────────────────────────────────────────────────
        "why_it_moved": {
            "type": "string",
            "description": "Plain-English explanation of today's price move. Use 'fell/dropped' for declines, 'surged/rose' for gains."
        },
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
        "why_it_moved", "key_catalysts", "catalyst_type", "sentiment",
        "is_sustained", "sustainability_reason", "analysis_confidence",
        "related_beneficiaries", "beneficiary_reasoning", "comparison_to_gainers",
        "outlook", "predicted_change_pct", "prediction_confidence", "time_horizon",
        "key_risks", "key_tailwinds", "valuation_signal", "growth_signal", "debt_signal",
    ],
}

_MOCK_RESPONSE: dict[str, Any] = {
    # Analysis
    "why_it_moved": (
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
        technicals_text: str | None = None,
        quarterly_text: str | None = None,
        growth_triggers_context: str | None = None,
    ) -> tuple[GainerAnalysis, StockPrediction | None]:
        """
        Single Gemini call that returns both a GainerAnalysis and a StockPrediction.
        ~40-50 % faster than two sequential calls.

        gainers_context:         top gainers from today's list — when supplied (i.e. the
                                 searched ticker is not in the gainer list) the model compares
                                 this stock against the day's winners.
        technicals_text:         pre-formatted technical analysis block from services/technicals.py
                                 injected directly into the Gemini prompt so the model factors
                                 RSI / MACD / SMA / volume into the 30-day prediction.
        growth_triggers_context: formatted summary of cached GrowthTriggersReport — when
                                 present, the model uses identified catalysts to calibrate
                                 the predicted_change_pct magnitude and confidence.
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
                why_it_moved=mock["why_it_moved"],
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
            ticker, change_pct, company_name, sector, news, fundamentals,
            gainers_context, technicals_text, quarterly_text, growth_triggers_context,
        )
        try:
            analysis = GainerAnalysis(
                ticker=ticker,
                # Support both new field name and old cached responses (backward compat)
                why_it_moved=raw.get("why_it_moved") or raw.get("why_it_gained", ""),
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
        technicals_text: str | None = None,
        quarterly_text: str | None = None,
        growth_triggers_context: str | None = None,
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

        # Step 1b: Quarterly earnings — confirms or contradicts fundamental quality
        quarterly_section = (
            "\n\nSTEP 1 — QUARTERLY EARNINGS TREND (confirm fundamental quality — drives base confidence):\n"
            + quarterly_text
        ) if quarterly_text else ""

        # Step 3: Technical — sizes and times the move, does not override direction
        tech_section = (
            "\n\nSTEP 3 — TECHNICAL SIGNALS (size and time the move — do not use to set direction):\n"
            + technicals_text
        ) if technicals_text else ""

        # Step 4: Growth triggers — calibrates magnitude and confidence if deep-dive is cached
        gt_section = (
            "\n\nSTEP 4 — GROWTH TRIGGERS (adjust magnitude and confidence):\n"
            + growth_triggers_context
        ) if growth_triggers_context else ""

        # Sign-aware labels for context only — direction is NOT the prediction anchor
        move_direction = "DECLINED" if change_pct < 0 else "GAINED"
        move_language_note = (
            "Use 'fell/dropped/declined/slid' language when describing today's move — never 'gained'."
            if change_pct < 0
            else "Use 'surged/rose/gained/climbed' language when describing today's move."
        )

        # Prompt section order: Fundamentals first (primary direction signal),
        # then Quarterly (confirms quality), Technical (sizes the move),
        # Growth Triggers (calibrates magnitude), News (closest to the instruction,
        # confirms or denies catalyst quality).
        prompt = (
            f"Stock: {company_name} ({ticker})\n"
            f"Sector: {sector or 'Unknown'}\n"
            f"Today's price action: {change_pct:+.1f}% ({move_direction})\n\n"
            "⚠️ REMEMBER: Today's direction does NOT determine the 30-day prediction.\n"
            "Classify the move (Category A/B/C) first, then use fundamentals to set direction.\n\n"
            f"STEP 2 — FUNDAMENTALS (primary 30-day direction signal):\n{fund_text}"
            + quarterly_section
            + f"\n\nSTEP 3 — TODAY'S CATALYST (classify: real fundamental shift, market noise, or speculative?):\n"
            f"{headlines or 'No news found — likely Category B/C (noise or speculative).'}"
            + tech_section
            + gt_section
            + gainers_section
            + f"\n\nTASK:\n"
            f"1. Classify today's move: Category A (fundamental), B (market noise), or C (speculative).\n"
            f"2. {move_language_note}\n"
            f"3. Set the 30-day prediction from fundamentals + earnings quality — NOT from today's {'decline' if change_pct < 0 else 'gain'}.\n"
            f"   {'If Category B/C decline: strong fundamentals → positive predicted_change_pct (recovery expected).' if change_pct < 0 else 'If Category B/C gain: weak fundamentals → negative predicted_change_pct (reversal expected).'}\n"
            f"4. Run the anti-bias checklist before outputting.\n"
            f"5. Identify 2-4 related beneficiary tickers.\n"
        )

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2500,   # combined schema needs ~1800-2200 tokens
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
                    "gainer_analyst.gemini_http_error",
                    ticker=ticker,
                    status=resp.status_code,
                    body=resp.text[:500],  # capture first 500 chars of error body
                )
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
