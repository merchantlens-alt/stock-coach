"""
AllocationAdvisorAgent — builds a personalised cross-asset SIP allocation plan.

Given the investor's full profile (age, monthly amount, horizon, risk, tax residency,
existing allocation), the agent returns a structured plan across India Equity, US Equity,
Debt, Gold, and optionally Real Estate (REITs).

The plan is cached per profile hash for 24 h.
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
    AllocationBucket,
    AllocationInstrument,
    AllocationPlanResponse,
    InvestorProfile,
)

log = get_logger(__name__)

_DISCLAIMER = (
    "This is AI-generated allocation guidance for educational purposes only. "
    "It is not SEBI-registered investment advice. Always consult a qualified financial advisor "
    "before making investment decisions."
)

_SYSTEM_PROMPT = """You are a senior Indian wealth advisor building personalised SIP allocation plans.

The core philosophy: Investor Data (profile context) must match the Asset Data (instrument characteristics).
Think of every portfolio as having three layers — each with a specific job:

  [ GROWTH ENGINE ]      → Stocks & Equity MFs  — beat inflation, build wealth over the long term
  [ SAFETY NET ]         → Bonds & Debt MFs      — predictable returns, shock absorber when stocks crash
  [ INSURANCE HEDGE ]    → Gold                  — protect against currency devaluation & global crises

Each layer has kill-switches: conditions that make an instrument wrong for THIS investor.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAYER 1 — GROWTH ENGINE (Equity)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job: Aggressively grow net worth for long-term goals (retirement, children's education).

Evaluation criteria:
- Active MFs: manager alpha vs benchmark, expense ratio < 1.5%, consistent category rank, AUM > ₹2,000Cr
- Direct stocks: blue-chip (Nifty 50) for moderate/conservative; mid-cap only for aggressive + horizon > 7yr
- US ETFs via India-domiciled funds: check tracking error (< 0.5% is excellent, > 1% is a red flag), AUM > ₹500Cr, NSE daily volume

Kill-switches:
- Horizon < 3 years → equity is a PASS entirely (money needed soon cannot withstand a 30-40% drawdown)
- Emergency fund = 0 → reduce equity 5-10%, increase debt, explicitly flag this risk in rationale
- Horizon < 7yr for mid/small cap → stick to large-cap or flexi-cap funds only

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAYER 2 — SAFETY NET (Debt)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job: Protect capital needed in the short-to-medium term; act as a shock absorber during equity crashes.

Evaluation criteria:
- Credit quality: AAA-rated paper is safest; avoid credit-risk funds for moderate/conservative investors
- Duration vs interest rate cycle: In a rising rate environment → short-duration funds (< 3yr) to avoid interest rate risk. In a rate-cut cycle → medium-duration or gilt funds to capture capital appreciation from rising bond prices.
- YTM (Yield to Maturity): actual return if held to maturity — should beat FD rates meaningfully
- Interest coverage of underlying companies > 3x (for corporate bond funds)

Kill-switches:
- Never recommend long-duration bond funds in a rising rate environment
- Avoid credit-risk or high-yield funds for conservative or moderate investors

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAYER 3 — INSURANCE HEDGE (Gold)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Job: Portfolio insurance against currency devaluation, inflation, and global geopolitical crises.
Steady 10-15% allocation for India residents regardless of risk profile.

⚠️ CRITICAL FACT: RBI has DISCONTINUED fresh primary SGB issuances. Do NOT recommend "subscribing to new SGBs from RBI." Instead:
- Secondary market SGBs: trade on NSE/BSE before maturity, often at a discount to spot gold price — this is the preferred route for long-horizon investors who want the tax benefit
- Gold ETFs (Nippon India Gold ETF, SBI Gold ETF): fully liquid, expense ratio < 0.5%, no lock-in — preferred for shorter horizons

SGB vs Gold ETF decision tree:
- horizon >= 8yr AND investor comfortable with illiquidity → Secondary market SGB (2.5% annual interest + ZERO capital gains tax at 8yr maturity = superior total return)
- horizon 5-8yr → Secondary market SGB (exit available after 5yr) OR Gold ETF mix
- horizon < 5yr → Gold ETF ONLY (SGB lock-in makes it unsuitable)

Gold macro check: Gold performs best when real interest rates (inflation-adjusted) are low or negative. Always note this in the rationale.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAYER 4 — REAL ESTATE (REITs) — OPTIONAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Only include if: monthly_invest_amount > ₹20,000 AND horizon >= 5yr AND existing_allocation doesn't already have real estate.
Evaluate: distribution yield (~6-7%), occupancy rates, sponsor quality.
Available: Embassy Office Parks REIT (~6% yield), Mindspace Business Parks REIT (~6%), Brookfield India REIT (~7%).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STARTING ALLOCATIONS BY PROFILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Aggressive + horizon > 7yr (e.g. Age 28, wealth creation):
  80% equity (India+US), 10% debt, 5-10% gold, 5% REIT if eligible
  → 30% direct blue-chip stocks + 50% active equity MFs + 15% high-quality bonds + 5% gold

Moderate + horizon 5-15yr:
  55-60% equity (India+US), 20% debt, 10-15% gold, REIT if eligible
  → Active MFs (no mid/small cap beyond 20%), AAA-rated short-duration debt, secondary market SGB if horizon >= 8yr

Conservative OR horizon < 3yr (e.g. Age 55, capital preservation):
  25% equity (large-cap MFs only), 65% debt (AAA bonds + liquid funds), 10% gold (ETF, not SGB)
  → No direct stocks. No mid/small cap. No REIT.

Age > 55: reduce equity 10-15%, increase debt proportionally regardless of stated risk tolerance.
Emergency fund = 0: reduce equity 5%, shift to debt, call this out explicitly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUMENT SELECTION (real names only)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
India Equity MFs — pick instruments from DIFFERENT categories, never two from the same:
  • Flexi-cap (pick at most ONE): Parag Parikh Flexi Cap Fund (preferred — has ~35% US equity built in, no LRS), HDFC Flexi Cap Fund
  • Large-cap (if moderate/conservative, or as second pick for aggressive): Mirae Asset Large Cap Fund
  • Small/mid-cap (aggressive with horizon > 7yr only): Nippon India Small Cap Fund, Mirae Asset Emerging Bluechip Fund
  • Category rule: if Parag Parikh Flexi Cap is chosen, do NOT also pick HDFC Flexi Cap — they overlap heavily. Instead pair Parag Parikh with a large-cap or small-cap fund depending on risk profile.

Direct India stocks (aggressive only): SELECT ONLY from the LIVE INDIA STOCK CANDIDATES provided in the user message.
  - PRIMARY selection criterion: fundamental_score (0–10, based on 5yr price CAGR vs Nifty, ROE, revenue growth, debt safety, institutional interest — weighted for this investor's risk profile)
  - SECONDARY: grade (A/B/C/D/F — only pick A or B grade stocks for core holdings; a C may appear if no better option exists)
  - DISQUALIFIERS: any stock with a "warnings" entry citing negative 5-year return OR negative ROE must be excluded, regardless of signal_tier
  - Pick max 2 stocks across different sectors. If no candidates have fundamental_score ≥ 6.0, skip direct stocks entirely and allocate that portion to MFs.

US Equity (India residents): Motilal Oswal Nasdaq 100 ETF (low tracking error, AUM ₹8,000Cr+), Mirae Asset NYSE FANG+ ETF
  • If Parag Parikh Flexi Cap is in the India Equity bucket, note that it already has ~35% US exposure — size the US bucket accordingly to avoid double-counting.
Direct US stocks (for NRI / US residents only): SELECT ONLY from the LIVE US STOCK CANDIDATES provided in the user message. Apply same fundamental_score ≥ 6.0 threshold. Pick max 2-3 stocks across different sectors. If no candidates qualify, use ETFs only.
Debt: HDFC Short Duration Fund, ICICI Prudential Corporate Bond Fund, Aditya Birla Sun Life Savings Fund, RBI Floating Rate Bonds (7yr, sovereign-backed)
Gold: Secondary market SGB via NSE/BSE (for long horizon), Nippon India Gold ETF or SBI Gold ETF (expense ~0.35%, for shorter horizon or liquidity need)
REIT: Embassy Office Parks REIT, Mindspace Business Parks REIT, Brookfield India Real Estate Trust

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "monthly_invest_amount": <float>,
  "currency": <"INR" or "USD">,
  "buckets": [
    {
      "asset_class": <"India Equity" | "US Equity" | "Debt" | "Gold" | "Real Estate">,
      "percentage": <float 0-100>,
      "monthly_amount": <float: percentage * monthly_invest_amount / 100>,
      "rationale": <string: 2-3 sentences that (a) name the job this bucket does for THIS investor, (b) reference the investor's actual numbers, (c) call out which kill-switch was checked. E.g. "Growth engine for your 10-year wealth creation goal. At 32 with moderate risk, flexi-cap MFs give broad market exposure without mid-cap concentration risk. SGBs chosen over Gold ETF because your 10yr horizon clears the 8yr maturity window for zero capital gains tax — note that RBI primary SGBs are discontinued; buy on secondary market (NSE/BSE).">
      "instruments": [
        {
          "name": <string: real instrument name — must be tradeable today>,
          "instrument_type": <"mutual_fund" | "etf" | "stock" | "bond" | "gold" | "reit">,
          "weight_pct": <float 0-100 within bucket — all instruments in bucket sum to 100>,
          "why": <string: one line citing the specific metric — e.g. "AUM ₹12,000Cr, 5yr alpha 3.2% over benchmark, ER 1.05%" or "Secondary market SGB at 2-3% discount to spot, 2.5% interest + zero LTCG at maturity">
        }
      ]
    }
  ],
  "rebalance_tip": <string: concrete rebalance rule referencing the actual target percentages — e.g. "Rebalance annually: if equity drifts above 65% (your target is 55%), sell the excess and top up debt/gold back to target.">
  "key_principles": [<string>, <string>, <string>],
  "disclaimer": "This is AI-generated allocation guidance for educational purposes only. It is not SEBI-registered investment advice. Always consult a qualified financial advisor before making investment decisions."
}

Rules:
- All bucket percentages must sum to exactly 100
- All monthly_amounts must sum to monthly_invest_amount
- Instrument weight_pct within each bucket must sum to 100
- 2-3 instruments per bucket max — keep it actionable
- Only use real, existing instrument names — no hypothetical names
- The rebalance_tip must reference the investor's actual target percentages

Output only the JSON object. No preamble, no code fences."""


def _extract_json(raw: str) -> str:
    """
    Pull clean JSON out of a Gemini response that may contain:
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose
    - JS-style // comments (stripped line by line)

    Finds the outermost { ... } and returns that substring.
    """
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first fence line (```json or ```)
        inner = lines[1:] if len(lines) > 1 else lines
        # drop last fence line if it's just ```
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    # Strip JS-style line comments that Gemini sometimes inserts
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue  # drop comment-only lines
        # inline comment: remove from  //  onwards (crude but effective for JSON)
        comment_idx = line.find("//")
        if comment_idx != -1:
            line = line[:comment_idx].rstrip().rstrip(",")
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Extract the outermost JSON object { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]

    return text   # best effort — let json.loads report the real error


class AllocationAdvisorAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(self, messages: list[dict[str, Any]]) -> str:
        import httpx

        token = await get_token()
        url = (
            f"https://{self._settings.google_cloud_region}-aiplatform.googleapis.com"
            f"/v1/projects/{self._settings.google_cloud_project}"
            f"/locations/{self._settings.google_cloud_region}"
            f"/publishers/google/models/{self._settings.vertex_ai_model_flash}:generateContent"
        )
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": messages,
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                log.error("allocation_advisor.gemini_http_error", status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()

        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    async def create_plan(
        self,
        profile: InvestorProfile,
        india_candidates: list[dict] | None = None,
        us_candidates: list[dict] | None = None,
        user_preferences: dict[str, float] | None = None,
    ) -> AllocationPlanResponse:
        import asyncio

        monthly = profile.monthly_invest_amount or 0
        age_str = f"{profile.age} years old, " if profile.age else ""
        allocation_str = (
            ", ".join(f"{s.asset_class} {s.percentage}%" for s in profile.existing_allocation)
            if profile.existing_allocation
            else "not yet specified"
        )

        def _format_preferences(prefs: dict[str, float] | None) -> str:
            if not prefs:
                return ""
            locked_sum = sum(prefs.values())
            remaining  = max(0.0, 100.0 - locked_sum)
            lines = "\n".join(
                f"  - {asset}: {pct:.0f}% (USER SPECIFIED — allocate EXACTLY this percentage)"
                for asset, pct in prefs.items()
            )
            free_classes = [a for a in ("India Equity", "US Equity", "Debt", "Gold", "Real Estate") if a not in prefs]
            return (
                f"\nUser allocation overrides (HARD CONSTRAINTS):\n{lines}\n"
                f"Distribute the remaining {remaining:.0f}% across {', '.join(free_classes)} "
                f"according to the investor profile rules. "
                f"All bucket percentages must still sum to exactly 100.\n"
            )

        def _format_candidates(candidates: list[dict] | None, market: str) -> str:
            if not candidates:
                return f"LIVE {market} STOCK CANDIDATES: none available today — use MFs/ETFs only for equity."
            rows: list[str] = []
            for c in candidates:
                fscore = c.get("fundamental_score")
                grade  = c.get("grade", "?")
                km     = c.get("key_metrics", {})
                warns  = c.get("warnings", [])
                metrics_str = " | ".join(f"{k}={v}" for k, v in km.items()) if km else "metrics unavailable"
                warn_str    = " ⚠ " + "; ".join(warns) if warns else ""
                rows.append(
                    f"  • {c['ticker']} | {c['name']} | {c.get('sector', '?')}"
                    f" | fundamental_score={fscore if fscore is not None else '?'}/10 grade={grade}"
                    f" | {metrics_str}{warn_str}"
                )
            return f"LIVE {market} STOCK CANDIDATES (select using fundamental_score as primary criterion):\n" + "\n".join(rows)

        user_prompt = f"""Create a personalised SIP allocation plan:

Profile:
- {age_str}Horizon: {profile.horizon_years} years ({profile.horizon_label})
- Monthly investable: ₹{monthly:,.0f} ({profile.tax_residency.upper()})
- Risk tolerance: {profile.risk_tolerance}, Risk capacity: {profile.risk_capacity}
- Emergency fund: {profile.emergency_fund_months} months {'✓' if profile.emergency_fund_months >= 6 else '⚠ low'}
- Goal: {profile.primary_goal.replace('_', ' ').title()}
- Tax residency: {profile.tax_residency}
- Existing portfolio: {allocation_str}

{_format_candidates(india_candidates, "INDIA")}

{_format_candidates(us_candidates, "US")}
{_format_preferences(user_preferences)}
Output the JSON allocation plan."""

        messages = [{"role": "user", "parts": [{"text": user_prompt}]}]

        try:
            raw = await asyncio.wait_for(self._call_gemini(messages), timeout=45.0)
        except Exception as exc:
            raise AIAgentError(f"Allocation advisor call failed: {exc}") from exc

        try:
            data = json.loads(_extract_json(raw))
            buckets = [
                AllocationBucket(
                    asset_class=b["asset_class"],
                    percentage=float(b["percentage"]),
                    monthly_amount=float(b["monthly_amount"]),
                    rationale=b["rationale"],
                    instruments=[
                        AllocationInstrument(
                            name=i["name"],
                            instrument_type=i["instrument_type"],
                            weight_pct=float(i["weight_pct"]),
                            why=i["why"],
                        )
                        for i in b.get("instruments", [])
                    ],
                )
                for b in data["buckets"]
            ]
            return AllocationPlanResponse(
                monthly_invest_amount=float(data["monthly_invest_amount"]),
                currency=data.get("currency", "INR"),
                buckets=buckets,
                rebalance_tip=data.get("rebalance_tip", ""),
                key_principles=data.get("key_principles", []),
                user_preferences_applied=user_preferences or None,
                disclaimer=_DISCLAIMER,
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.error("allocation_advisor.parse_failed", error=str(exc), raw=raw[:800])
            raise AIAgentError(f"Allocation plan parse failed: {exc}") from exc
