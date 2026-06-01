"""
GrowthTriggersAgent — institutional-style research note with 3-5 specific
business growth triggers, P&L timelines, and HIGH/MEDIUM/OPTIONALITY
conviction tags.

Design
──────
• One Vertex AI call with Google Search grounding so data is fresh.
• Grounding conflicts with responseSchema/responseMimeType → JSON requested
  in prompt text, parsed manually.
• 24-hour cache (results are research documents, not real-time).
• Falls back to a minimal stub report on Gemini failure.
• Cost: ~$0.001-0.003 per call (grounded, pro model).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.auth import get_token
from core.config import Settings
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import (
    FundamentalsData,
    GrowthTrigger,
    GrowthTriggersReport,
    Market,
    RiskItem,
    ScorecardRow,
)

log = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are an institutional equity analyst (Kotak/Motilal/Ambit caliber) writing a Growth Triggers research note for retail investors.

Guidelines:
- Cite specific numbers: revenue, margin %, market share shifts, contract values
- All timelines must be concrete: "Q2 FY26", "H2 2025", not "soon" or "eventually"
- P&L impact must be quantified: "adds 150-200 bps to EBITDA margin" or "could add $200M to revenue"
- Conviction levels: HIGH = near-certain earnings driver, MEDIUM = likely but dependent on execution, OPTIONALITY = high-upside if conditions align
- Use plain English — no jargon, no disclaimers inside the JSON
- Return ONLY valid JSON — no markdown, no code blocks, no preamble\
"""


def _build_prompt(
    ticker: str,
    name: str,
    market: Market,
    price: float,
    fundamentals: Optional[FundamentalsData],
    news_headlines: list[str],
    quarterly_summary: Optional[str],
) -> str:
    currency = "₹" if market == "india" else "$"
    market_label = "Indian (NSE/BSE)" if market == "india" else "US (NYSE/NASDAQ)"
    revenue_unit = "Cr" if market == "india" else "M"

    lines: list[str] = [
        f"Company: {ticker} ({name})",
        f"Market: {market_label}",
        f"Current Price: {currency}{price:,.2f}",
    ]

    if fundamentals:
        f = fundamentals
        if f.market_cap_value:
            cap = f.market_cap_value
            if market == "india":
                cap_str = f"₹{cap/1e7:,.0f} Cr"
            else:
                cap_str = f"${cap/1e9:.1f}B" if cap >= 1e9 else f"${cap/1e6:.0f}M"
            lines.append(f"Market Cap: {cap_str}")

        if f.ttm_revenue:
            rev = f.ttm_revenue
            if market == "india":
                rev_str = f"₹{rev/1e7:,.0f} Cr"
            else:
                rev_str = f"${rev/1e6:.0f}M"
            lines.append(f"TTM Revenue: {rev_str}")

        if f.ebitda_margin is not None:
            lines.append(f"EBITDA Margin: {f.ebitda_margin * 100:.1f}%")
        elif f.profit_margin is not None:
            lines.append(f"Net Profit Margin: {f.profit_margin * 100:.1f}%")

        if f.revenue_growth_yoy is not None:
            lines.append(f"Revenue Growth (YoY): {f.revenue_growth_yoy * 100:+.1f}%")

        if f.pe_ratio is not None:
            lines.append(f"Trailing P/E: {f.pe_ratio:.1f}x")
        if f.forward_pe is not None:
            lines.append(f"Forward P/E: {f.forward_pe:.1f}x")

        if f.insider_holding_pct is not None:
            lines.append(f"Insider Holding: {f.insider_holding_pct * 100:.1f}%")

        if f.analyst_recommendation:
            lines.append(f"Analyst Consensus: {f.analyst_recommendation}")
        if f.analyst_target_price is not None:
            lines.append(f"Analyst Target: {currency}{f.analyst_target_price:.2f}")

        if f.roe is not None:
            lines.append(f"ROE: {f.roe * 100:.1f}%")
        if f.debt_equity is not None:
            lines.append(f"Debt/Equity: {f.debt_equity:.2f}x")

    if quarterly_summary:
        lines.append(f"\nQuarterly Trend:\n{quarterly_summary}")

    if news_headlines:
        lines.append("\nRecent Headlines:")
        for h in news_headlines[:5]:
            lines.append(f"  • {h}")

    company_block = "\n".join(lines)

    return f"""{company_block}

---

Use Google Search to find the latest earnings call highlights, analyst notes, and business developments for {ticker}.

Write a Growth Triggers research note as a JSON object with exactly this structure:

{{
  "company_snapshot": "3-4 sentences covering: (1) what the company does and its competitive moat, (2) what changed recently to put it on the radar, (3) revenue/{revenue_unit} and margin snapshot with trend, (4) what valuation the market is currently paying",
  "triggers": [
    {{
      "name": "Trigger Name (2-4 words, title case)",
      "what": "Plain English: what this business lever is and why it's emerging now",
      "p_and_l_impact": "Quantified impact: e.g. 'Adds 180-220 bps to EBITDA margin by FY27' or 'Could add {currency}400M in incremental revenue'",
      "timeline": "Specific period: e.g. 'Q3 FY26', 'H2 2025', 'Next 2-3 quarters'",
      "conviction": "HIGH or MEDIUM or OPTIONALITY",
      "watch_for": "The one metric or event to track: e.g. 'Gross margin crossing 45%' or 'Next quarterly order intake'"
    }}
  ],
  "already_in_price": "2-3 sentences: what the current valuation implies the market has already baked in — be specific about the implied growth rate or margin assumption",
  "upside_scenario": "2-3 sentences: what additional upside is available if the triggers play out — quantify if possible (e.g. '15-20% upside to consensus')",
  "key_risks": [
    {{
      "name": "Risk Name (2-4 words)",
      "what": "What this risk is in plain English",
      "why_it_matters": "How it could impact the P&L or stock price if it materialises"
    }}
  ],
  "scorecard": [
    {{"dimension": "Revenue Growth", "rating": "Strong|Moderate|Weak", "note": "One-sentence justification"}},
    {{"dimension": "Margin Expansion", "rating": "Strong|Moderate|Weak", "note": "One-sentence justification"}},
    {{"dimension": "Valuation vs Peers", "rating": "Rich|Fair|Cheap", "note": "One-sentence justification"}},
    {{"dimension": "Management Track Record", "rating": "Strong|Moderate|Weak", "note": "One-sentence justification"}},
    {{"dimension": "Downside Protection", "rating": "Strong|Moderate|Weak", "note": "One-sentence justification"}}
  ]
}}

Requirements:
- 3-5 triggers (minimum 3, maximum 5)
- 2-3 risks (minimum 2, maximum 3)
- Exactly 5 scorecard rows
- All timelines must be specific calendar periods
- All P&L impacts must be quantified with numbers
- Return ONLY the JSON object — no markdown, no code fences"""


def _fallback_report(ticker: str, market: Market) -> GrowthTriggersReport:
    """Minimal fallback when Gemini fails — marked is_error=True so the route skips caching."""
    return GrowthTriggersReport(
        ticker=ticker,
        market=market,
        is_error=True,
        company_snapshot=(
            f"{ticker} is a publicly listed company. "
            "Our AI research engine encountered an issue generating the full growth analysis. "
            "Please tap 'Retry' to try again."
        ),
        triggers=[
            GrowthTrigger(
                name="AI Analysis Unavailable",
                what="The growth triggers analysis could not be generated at this time.",
                p_and_l_impact="Please retry",
                timeline="Retry now",
                conviction="MEDIUM",
                watch_for="Tap retry to regenerate",
            )
        ],
        already_in_price="Analysis unavailable — please retry.",
        upside_scenario="Analysis unavailable — please retry.",
        key_risks=[
            RiskItem(
                name="Analysis Unavailable",
                what="The AI research service encountered an error.",
                why_it_matters="Tap retry to generate fresh analysis.",
            )
        ],
        scorecard=[
            ScorecardRow(dimension="Revenue Growth", rating="Unknown", note="Data unavailable"),
            ScorecardRow(dimension="Margin Expansion", rating="Unknown", note="Data unavailable"),
            ScorecardRow(dimension="Valuation vs Peers", rating="Unknown", note="Data unavailable"),
            ScorecardRow(dimension="Management Track Record", rating="Unknown", note="Data unavailable"),
            ScorecardRow(dimension="Downside Protection", rating="Unknown", note="Data unavailable"),
        ],
    )


def _parse_json_from_text(text: str) -> dict[str, Any]:
    """Extract JSON from Gemini response that may have prose around it."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Extract first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError("No valid JSON found in Gemini response")


class GrowthTriggersAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock = settings.mock_ai

    async def generate(
        self,
        ticker: str,
        name: str,
        market: Market,
        price: float,
        fundamentals: Optional[FundamentalsData] = None,
        news_headlines: Optional[list[str]] = None,
        quarterly_summary: Optional[str] = None,
    ) -> GrowthTriggersReport:
        """
        Generate a Growth Triggers research note. Always returns a report —
        falls back to a minimal stub on Gemini failure.
        """
        if self._mock:
            return self._mock_report(ticker, market, price)

        try:
            return await self._call_gemini(
                ticker, name, market, price, fundamentals,
                news_headlines or [], quarterly_summary,
            )
        except Exception as exc:
            log.warning("growth_triggers.gemini_failed", ticker=ticker, error=str(exc))
            return _fallback_report(ticker, market)

    def _mock_report(self, ticker: str, market: Market, price: float) -> GrowthTriggersReport:
        currency = "₹" if market == "india" else "$"
        return GrowthTriggersReport(
            ticker=ticker,
            market=market,
            company_snapshot=(
                f"{ticker} is a leading company in its sector with a strong competitive moat built "
                f"over several years. Recent developments have put it on institutional radars — "
                f"management guided for double-digit revenue growth in the coming fiscal year. "
                f"At {currency}{price:,.2f}, the market is pricing in moderate growth with limited upside assumptions."
            ),
            triggers=[
                GrowthTrigger(
                    name="Market Share Expansion",
                    what="The company is gaining share from weaker competitors through superior product quality and distribution reach.",
                    p_and_l_impact="Could add 8-12% incremental revenue over the next 2 fiscal years.",
                    timeline="Q2-Q3 FY26",
                    conviction="HIGH",
                    watch_for="Sequential revenue growth >5% for 2 consecutive quarters",
                ),
                GrowthTrigger(
                    name="Operating Leverage",
                    what="Fixed cost base is largely covered; incremental revenue flows at 60-70% gross margin.",
                    p_and_l_impact="Every 10% revenue growth adds ~200 bps to EBITDA margin.",
                    timeline="Next 3-4 quarters",
                    conviction="MEDIUM",
                    watch_for="EBITDA margin crossing 25% on a TTM basis",
                ),
                GrowthTrigger(
                    name="New Product Cycle",
                    what="A next-generation product line is expected to launch, targeting a higher-value customer segment.",
                    p_and_l_impact="Premium pricing could drive ASP up 15-20%, boosting blended margins.",
                    timeline="H2 FY26",
                    conviction="OPTIONALITY",
                    watch_for="Official product launch announcement and initial order disclosures",
                ),
            ],
            already_in_price=(
                "At current valuation, the market appears to be pricing in stable mid-single-digit growth "
                "with flat margins. There is little credit given for the expansion initiatives or new "
                "product pipeline — this creates a potential re-rating opportunity."
            ),
            upside_scenario=(
                "If the market share gains and operating leverage play out as guided, there could be "
                "15-25% upside to current consensus estimates over 12-18 months. A valuation re-rating "
                "from current multiples towards sector leaders could add further upside."
            ),
            key_risks=[
                RiskItem(
                    name="Competitive Pressure",
                    what="Larger well-funded competitors could accelerate their market response.",
                    why_it_matters="Could compress pricing power and delay the margin expansion thesis by 2-3 quarters.",
                ),
                RiskItem(
                    name="Macro Slowdown",
                    what="A demand slowdown in the primary end market could reduce volume growth.",
                    why_it_matters="Would likely cause consensus estimates to be cut 10-15%, pressuring the stock.",
                ),
            ],
            scorecard=[
                ScorecardRow(dimension="Revenue Growth", rating="Strong", note="Double-digit growth guidance with improving visibility."),
                ScorecardRow(dimension="Margin Expansion", rating="Moderate", note="Operating leverage building but needs 2-3 quarters to materialise."),
                ScorecardRow(dimension="Valuation vs Peers", rating="Fair", note="Inline with sector median — re-rating possible if execution is strong."),
                ScorecardRow(dimension="Management Track Record", rating="Strong", note="Consistent delivery on guidance over past 3 years."),
                ScorecardRow(dimension="Downside Protection", rating="Moderate", note="Balance sheet is strong; limited leverage provides cushion."),
            ],
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(
        self,
        ticker: str,
        name: str,
        market: Market,
        price: float,
        fundamentals: Optional[FundamentalsData],
        news_headlines: list[str],
        quarterly_summary: Optional[str],
    ) -> GrowthTriggersReport:
        import asyncio

        prompt = _build_prompt(
            ticker, name, market, price, fundamentals,
            news_headlines, quarterly_summary,
        )

        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # Google Search grounding — gives the model access to live web data so it
            # can cite real earnings figures, analyst targets, and recent developments.
            # Note: grounding is incompatible with responseMimeType=application/json,
            # so JSON is requested in the prompt text and parsed via _parse_json_from_text.
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2500,
                # Disable thinking — the Google Search round-trip already adds
                # significant latency; thinking on top pushes past the timeout.
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

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                log.error(
                    "growth_triggers.gemini_http_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
            resp.raise_for_status()

        raw = resp.json()
        try:
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            log.error("growth_triggers.bad_response_shape", error=str(exc), raw=str(raw)[:300])
            raise AIAgentError(f"Bad Gemini response shape: {exc}") from exc

        try:
            data = _parse_json_from_text(text)
        except (ValueError, json.JSONDecodeError) as exc:
            log.error("growth_triggers.parse_error", error=str(exc), snippet=text[:300])
            raise AIAgentError(f"Growth triggers JSON parse error: {exc}") from exc

        try:
            report = GrowthTriggersReport(
                ticker=ticker,
                market=market,
                company_snapshot=data.get("company_snapshot", ""),
                triggers=[
                    GrowthTrigger(**t) for t in data.get("triggers", [])
                ],
                already_in_price=data.get("already_in_price", ""),
                upside_scenario=data.get("upside_scenario", ""),
                key_risks=[
                    RiskItem(**r) for r in data.get("key_risks", [])
                ],
                scorecard=[
                    ScorecardRow(**s) for s in data.get("scorecard", [])
                ],
            )
        except Exception as exc:
            log.error("growth_triggers.schema_error", error=str(exc))
            raise AIAgentError(f"Growth triggers schema validation failed: {exc}") from exc

        log.info(
            "growth_triggers.gemini_ok",
            ticker=ticker,
            market=market,
            triggers=len(report.triggers),
        )
        return report
