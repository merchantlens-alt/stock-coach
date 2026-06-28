"""
AllocationAdvisorAgent — Multi-agent pipeline for cross-asset SIP allocation plans.

Pipeline (Phase 1 runs in parallel, Phase 2 assembles in Python):
  Agent 1 — StockPicker    : selects best stocks from fundamentals-enriched candidates
  Agent 2 — FundSelector   : picks MFs, ETFs, debt, gold, REIT instruments
  Agent 3 — Allocator      : determines % splits across asset classes

  Phase 2 (Python, no extra Gemini call):
  _synthesize_plan()        : merges outputs into AllocationPlanResponse
"""
from __future__ import annotations

import asyncio
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

# ── System prompts (focused, one job each) ─────────────────────────────────────

_STOCK_PICKER_SYSTEM = """You are a quality-at-a-reasonable-price (QARP) equity analyst. Your ONLY job: select the best stocks from the provided candidates for a SIP portfolio. Every candidate is already a fundamentally screened name trading BELOW its 52-week high — your edge is buying quality on a dip, NOT chasing the highest-quality name regardless of price.

Each candidate row carries: fundamental_score (0–10), grade, dip% (how far below its 52-week high), dip_quality (0–10, higher = bigger/better discount), composite (quality × dip blend).

Selection rules:
- PRIMARY criterion: composite score — it already blends quality (0.6) with the size of the dip (0.4). Rank candidates by composite, highest first.
- QUALITY FLOOR: never pick a stock with fundamental_score < 5.5 or grade worse than C, no matter how deep the dip — a falling knife is not a bargain.
- PREFER A/B grade. A C-grade name is acceptable ONLY when its dip is steep (dip_quality >= 6) AND fundamentals are stable (no disqualifying warnings).
- DISQUALIFIER: skip any stock with "negative 5-year return" OR "negative ROE" in warnings — a dip on a deteriorating business is a value trap, not an opportunity.
- VALUATION CHECK: a steep dip does NOT make an expensive stock cheap. If a candidate carries a "P/B" or "P/E" warning, or its key_metrics show price_to_book above ~8x, treat the dip as LOW margin of safety and down-rank it versus similarly-graded names at reasonable multiples. Only override this if the dip is exceptional (dip_quality >= 8) AND the business is best-in-class.
- Tie-break between similar composite scores using the higher fundamental_score.
- Diversification: no two stocks from the same sector.
- For conservative profile: return empty lists — no direct stocks.
- For moderate: max 2 India stocks (large-cap sectors only), max 1 US stock.
- For aggressive with horizon > 7yr: max 3 India + 2 US stocks.
- weight_pct is the recommended % of this stock WITHIN its equity bucket (India or US). Stocks within a single market must sum to ≤ 50 (rest goes to MFs). If only one stock, assign it 30-40%.
- In each "why", cite the dip explicitly (e.g. "−22% off 52w high") alongside the quality evidence — that is the whole thesis.
- If no candidates clear the quality floor, return empty lists.

Output ONLY this JSON (no prose, no fences):
{
  "india_picks": [
    {"ticker": "TCS.NS", "name": "Tata Consultancy Services", "instrument_type": "stock", "sector": "IT", "weight_pct": 35, "why": "fundamental_score=8.5/10 grade=A trading −22% off 52w high (dip_quality 8/10); 5yr CAGR 18% vs Nifty 13%, ROE 28%, zero debt warnings — quality on sale"}
  ],
  "us_picks": [
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "instrument_type": "stock", "sector": "Semiconductors", "weight_pct": 40, "why": "..."}
  ],
  "skip_reason": null
}"""

_FUND_SELECTOR_SYSTEM = """You are an Indian mutual fund and ETF advisor. Your ONLY job: select specific, real, tradeable instruments for each asset class.

Available instruments:

India Equity MFs (pick instruments from DIFFERENT categories, at most ONE per category):
  • Flexi-cap (ONE only): Parag Parikh Flexi Cap Fund (preferred — ~35% US equity built in), HDFC Flexi Cap Fund
  • Large-cap: Mirae Asset Large Cap Fund
  • Small/mid-cap (aggressive, horizon > 7yr only): Nippon India Small Cap Fund, Mirae Asset Emerging Bluechip Fund
  • RULE: if Parag Parikh Flexi Cap is chosen, do NOT also pick HDFC Flexi Cap. Pair Parag Parikh with large-cap or small-cap instead.

US Instruments (India residents):
  • Motilal Oswal Nasdaq 100 ETF (preferred — pick the highest-AUM, lowest-tracking-error broad US tech ETF)
  • Mirae Asset NYSE FANG+ ETF
  • If Parag Parikh Flexi Cap is in India Equity, it already carries meaningful US exposure — size US bucket accordingly.

Debt:
  • HDFC Short Duration Fund (rising rate env → short duration)
  • ICICI Prudential Corporate Bond Fund
  • Aditya Birla Sun Life Savings Fund
  • RBI Floating Rate Bonds (7yr, sovereign — for capital preservation investors)
  • NEVER recommend long-duration bond funds in a rising rate environment
  • For conservative/moderate: no credit-risk or high-yield funds

Gold:
  • Secondary Market SGB via NSE/BSE (horizon >= 8yr — 2.5% annual interest + zero LTCG at maturity)
  • Nippon India Gold ETF or SBI Gold ETF (horizon < 8yr or liquidity needed)
  • NOTE: RBI has discontinued NEW SGB primary issuances — recommend secondary market route only

REIT (ALWAYS return 2-3 candidates — the allocator decides whether the bucket gets any weight; you only supply the menu):
  • Embassy Office Parks REIT
  • Mindspace Business Parks REIT
  • Brookfield India Real Estate Trust
  Do NOT quote a specific yield % — yields move; describe the instrument, not a stale number.

weight_pct = % of this instrument within its own bucket (all instruments in same bucket must sum to 100).

Output ONLY this JSON (no prose, no fences):
{
  "india_mfs": [
    {"name": "Parag Parikh Flexi Cap Fund", "instrument_type": "mutual_fund", "weight_pct": 100, "why": "Flexi-cap with built-in 35% US exposure; no need for separate international ETF at this allocation size"}
  ],
  "us_instruments": [
    {"name": "Motilal Oswal Nasdaq 100 ETF", "instrument_type": "etf", "weight_pct": 100, "why": "Highest-AUM, lowest-tracking-error route to liquid US tech exposure via NSE"}
  ],
  "debt": [
    {"name": "HDFC Short Duration Fund", "instrument_type": "mutual_fund", "weight_pct": 60, "why": "AAA-rated short duration; safe in current rate environment"},
    {"name": "RBI Floating Rate Bonds", "instrument_type": "bond", "weight_pct": 40, "why": "Sovereign-backed, floating rate protects against rate rises, 7yr lock-in suits the horizon"}
  ],
  "gold": [
    {"name": "Secondary Market SGB via NSE/BSE", "instrument_type": "gold", "weight_pct": 100, "why": "Horizon >= 8yr clears the maturity window — 2.5% annual interest + zero LTCG tax at redemption, typically trades near or below spot gold"}
  ],
  "reit": [
    {"name": "Embassy Office Parks REIT", "instrument_type": "reit", "weight_pct": 60, "why": "Largest listed office REIT; diversified Grade-A tenants. Include only if the allocator assigns Real Estate a non-zero weight"},
    {"name": "Mindspace Business Parks REIT", "instrument_type": "reit", "weight_pct": 40, "why": "Quality office portfolio across Mumbai/Hyderabad; complements Embassy for diversification"}
  ]
}"""

_ALLOCATOR_SYSTEM = """You are a portfolio allocation strategist. Your ONLY job: given an investor profile, decide the percentage split across asset classes. Apply ALL rules below strictly. All percentages must sum to EXACTLY 100.

Starting allocations:
  Aggressive + horizon > 7yr:   India Equity 55-60%, US Equity 10-15%, Debt 10-15%, Gold 5-10%, REIT 0-5%
  Moderate + horizon 5-15yr:    India Equity 40-50%, US Equity 5-10%,  Debt 20-25%, Gold 10-15%, REIT 0-5%
  Conservative OR horizon < 3yr: India Equity 15-25%, US Equity 0%,    Debt 55-65%, Gold 10%,    REIT 0%

Kill-switches (apply before outputting):
  - Horizon < 3yr → reduce equity to max 20% total; skip US equity; skip REIT
  - Horizon < 7yr → no mid/small cap; reduce India Equity 5% vs starting point
  - Emergency fund = 0 → reduce India Equity by 5%, increase Debt by 5%
  - Age > 55 → reduce equity 10-15% vs starting, increase Debt proportionally
  - Monthly invest < ₹20,000 OR horizon < 5yr → REIT = 0%
  - Conservative investor → US Equity = 0%

Rationale for each bucket must be 2-3 sentences referencing actual investor numbers.

Output ONLY this JSON (no prose, no fences):
{
  "allocations": {"India Equity": 55, "US Equity": 10, "Debt": 20, "Gold": 10, "Real Estate": 5},
  "rationales": {
    "India Equity": "Core growth engine for your 10-year wealth creation goal. At 35 with aggressive risk tolerance and adequate 6-month emergency fund, 55% equity is appropriate. Flexi-cap + direct stocks for maximum alpha.",
    "US Equity": "10% global diversification via NASDAQ ETF. Parag Parikh already carries 35% US exposure internally — this 10% is additive, not duplicative.",
    "Debt": "20% safety net. Short-duration funds appropriate in current rate environment. AAA-rated paper only for this profile.",
    "Gold": "10% insurance hedge against currency devaluation. Gold performs best when real rates are low — current environment is supportive.",
    "Real Estate": "5% REIT allocation: monthly amount > ₹20,000 and horizon > 5yr both pass the inclusion thresholds."
  },
  "rebalance_tip": "Rebalance annually: if India Equity drifts above 65% (target 55%), trim equity and top up Debt/Gold to restore targets.",
  "key_principles": ["Stay invested through market cycles — compounding works over 10 years, not 10 months", "Rebalance annually to prevent equity drift above 65%", "Never redeem debt/gold positions to fund lifestyle expenses — they are your shock absorber"]
}"""


def _extract_json(raw: str) -> str:
    """Pull clean JSON from Gemini output that may have code fences or JS // comments."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if len(lines) > 1 else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        comment_idx = line.find("//")
        if comment_idx != -1:
            line = line[:comment_idx].rstrip().rstrip(",")
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _normalize_weights(instruments: list[dict]) -> list[dict]:
    """Scale instrument weight_pct values so they sum to exactly 100."""
    if not instruments:
        return instruments
    total = sum(i.get("weight_pct", 0) for i in instruments)
    if total <= 0:
        equal = round(100.0 / len(instruments), 1)
        for i in instruments:
            i["weight_pct"] = equal
    elif abs(total - 100.0) > 0.5:
        scale = 100.0 / total
        for i in instruments:
            i["weight_pct"] = round((i.get("weight_pct", 0) * scale), 1)
        # Fix rounding drift on last item
        drift = 100.0 - sum(i["weight_pct"] for i in instruments)
        if drift and instruments:
            instruments[-1]["weight_pct"] = round(instruments[-1]["weight_pct"] + drift, 1)
    return instruments


def _to_instruments(items: list[dict]) -> list[AllocationInstrument]:
    return [
        AllocationInstrument(
            name=i["name"],
            instrument_type=i["instrument_type"],
            weight_pct=float(i.get("weight_pct", 0)),
            why=i.get("why", ""),
        )
        for i in items
    ]


class AllocationAdvisorAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
    async def _call_gemini(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        temperature: float = 0.15,
    ) -> str:
        import httpx

        token = await get_token()
        url = (
            f"https://{self._settings.google_cloud_region}-aiplatform.googleapis.com"
            f"/v1/projects/{self._settings.google_cloud_project}"
            f"/locations/{self._settings.google_cloud_region}"
            f"/publishers/google/models/{self._settings.vertex_ai_model_flash}:generateContent"
        )
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": messages,
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                log.error("allocation_advisor.gemini_http_error", status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()

        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # ── Agent 1: Stock Picker ──────────────────────────────────────────────────

    async def _pick_stocks(
        self,
        profile: InvestorProfile,
        india_candidates: list[dict],
        us_candidates: list[dict],
    ) -> dict:
        def _fmt(candidates: list[dict], market: str) -> str:
            if not candidates:
                return f"LIVE {market} CANDIDATES: none available today."
            rows = []
            for c in candidates:
                fscore = c.get("fundamental_score")
                grade  = c.get("grade", "?")
                km     = c.get("key_metrics", {})
                warns  = c.get("warnings", [])
                dip    = c.get("pct_from_52w_high")
                dip_q  = c.get("dip_quality")
                comp   = c.get("composite_score")
                metrics_str = " | ".join(f"{k}={v}" for k, v in km.items()) if km else "metrics unavailable"
                warn_str    = " ⚠ " + "; ".join(warns) if warns else ""
                dip_str = f"dip={dip:.0f}%" if isinstance(dip, (int, float)) else "dip=?"
                dipq_str = f"dip_quality={dip_q:.1f}/10" if isinstance(dip_q, (int, float)) else ""
                comp_str = f"composite={comp:.1f}" if isinstance(comp, (int, float)) else ""
                rows.append(
                    f"  • {c['ticker']} | {c['name']} | {c.get('sector', '?')}"
                    f" | score={fscore if fscore is not None else '?'}/10 grade={grade}"
                    f" | {dip_str} {dipq_str} {comp_str}".rstrip()
                    + f" | {metrics_str}{warn_str}"
                )
            return f"LIVE {market} CANDIDATES (already screened: fundamentally sound, trading below 52w high):\n" + "\n".join(rows)

        age_str = f", age {profile.age}" if profile.age else ""
        user_msg = (
            f"Investor: {profile.risk_tolerance} risk{age_str}, horizon {profile.horizon_years}yr, "
            f"emergency fund {profile.emergency_fund_months}m.\n\n"
            f"{_fmt(india_candidates, 'INDIA')}\n\n"
            f"{_fmt(us_candidates, 'US')}\n\n"
            "Select stocks per rules. Output only the JSON."
        )
        try:
            raw = await asyncio.wait_for(
                self._call_gemini([{"role": "user", "parts": [{"text": user_msg}]}], _STOCK_PICKER_SYSTEM),
                timeout=35.0,
            )
            return json.loads(_extract_json(raw))
        except Exception as exc:
            log.warning("allocation_advisor.stock_picker_failed", error=str(exc))
            return {"india_picks": [], "us_picks": [], "skip_reason": str(exc)}

    # ── Agent 2: Fund Selector ─────────────────────────────────────────────────

    async def _select_funds(self, profile: InvestorProfile) -> dict:
        monthly = profile.monthly_invest_amount or 0
        allocation_str = (
            ", ".join(f"{s.asset_class} {s.percentage}%" for s in profile.existing_allocation)
            if profile.existing_allocation else "not yet specified"
        )
        user_msg = (
            f"Investor profile:\n"
            f"- Risk: {profile.risk_tolerance}, Capacity: {profile.risk_capacity}\n"
            f"- Horizon: {profile.horizon_years}yr ({profile.horizon_label})\n"
            f"- Monthly invest: ₹{monthly:,.0f}\n"
            f"- Tax residency: {profile.tax_residency}\n"
            f"- Emergency fund: {profile.emergency_fund_months} months\n"
            f"- Existing allocation: {allocation_str}\n"
            f"- Goal: {profile.primary_goal.replace('_', ' ').title()}\n\n"
            "Select instruments per rules. Output only the JSON."
        )
        try:
            raw = await asyncio.wait_for(
                self._call_gemini([{"role": "user", "parts": [{"text": user_msg}]}], _FUND_SELECTOR_SYSTEM),
                timeout=35.0,
            )
            return json.loads(_extract_json(raw))
        except Exception as exc:
            log.error("allocation_advisor.fund_selector_failed", error=str(exc))
            raise AIAgentError(f"Fund selector failed: {exc}") from exc

    # ── Agent 3: Allocator ─────────────────────────────────────────────────────

    async def _determine_allocations(
        self,
        profile: InvestorProfile,
        user_preferences: dict[str, float] | None,
    ) -> dict:
        monthly = profile.monthly_invest_amount or 0
        pref_str = ""
        if user_preferences:
            locked_sum = sum(user_preferences.values())
            remaining  = max(0.0, 100.0 - locked_sum)
            free_classes = [a for a in ("India Equity", "US Equity", "Debt", "Gold", "Real Estate") if a not in user_preferences]
            lines = "\n".join(
                f"  - {asset}: {pct:.0f}% (USER-SPECIFIED — use EXACTLY this %)"
                for asset, pct in user_preferences.items()
            )
            pref_str = (
                f"\nHARD CONSTRAINTS from user (override starting allocations):\n{lines}\n"
                f"Distribute remaining {remaining:.0f}% across {', '.join(free_classes)} per profile rules. "
                f"Total must still sum to 100.\n"
            )

        age_str = f", age {profile.age}" if profile.age else ""
        user_msg = (
            f"Investor profile:\n"
            f"- Risk tolerance: {profile.risk_tolerance}, Capacity: {profile.risk_capacity}\n"
            f"- Horizon: {profile.horizon_years}yr ({profile.horizon_label}){age_str}\n"
            f"- Monthly invest: ₹{monthly:,.0f}\n"
            f"- Emergency fund: {profile.emergency_fund_months} months "
            f"{'✓' if profile.emergency_fund_months >= 6 else '⚠ low'}\n"
            f"- Goal: {profile.primary_goal.replace('_', ' ').title()}\n"
            f"- Tax residency: {profile.tax_residency}\n"
            f"{pref_str}\n"
            "Determine allocations per rules. All percentages must sum to 100. Output only the JSON."
        )
        try:
            raw = await asyncio.wait_for(
                self._call_gemini([{"role": "user", "parts": [{"text": user_msg}]}], _ALLOCATOR_SYSTEM),
                timeout=35.0,
            )
            return json.loads(_extract_json(raw))
        except Exception as exc:
            log.error("allocation_advisor.allocator_failed", error=str(exc))
            raise AIAgentError(f"Allocator failed: {exc}") from exc

    # ── Python synthesis (no extra Gemini call) ────────────────────────────────

    def _synthesize_plan(
        self,
        profile: InvestorProfile,
        stock_picks: dict,
        fund_picks: dict,
        allocation_data: dict,
        user_preferences: dict[str, float] | None,
    ) -> AllocationPlanResponse:
        monthly = profile.monthly_invest_amount or 0
        allocations = allocation_data.get("allocations", {})
        rationales  = allocation_data.get("rationales", {})

        buckets: list[AllocationBucket] = []

        def _build_bucket(asset_class: str, instruments: list[dict]) -> AllocationBucket | None:
            pct = allocations.get(asset_class, 0)
            if pct <= 0:
                return None
            instruments = _normalize_weights([dict(i) for i in instruments])
            return AllocationBucket(
                asset_class=asset_class,
                percentage=float(pct),
                monthly_amount=round(monthly * pct / 100, 2),
                rationale=rationales.get(asset_class, ""),
                instruments=_to_instruments(instruments),
            )

        # India Equity: stocks + MFs combined
        india_instruments = list(stock_picks.get("india_picks", []) or []) + list(fund_picks.get("india_mfs", []) or [])
        if india_instruments:
            b = _build_bucket("India Equity", india_instruments)
            if b:
                buckets.append(b)

        # US Equity: US stocks + ETFs combined
        us_instruments = list(stock_picks.get("us_picks", []) or []) + list(fund_picks.get("us_instruments", []) or [])
        if us_instruments:
            b = _build_bucket("US Equity", us_instruments)
            if b:
                buckets.append(b)

        # Debt
        debt = fund_picks.get("debt", []) or []
        if debt:
            b = _build_bucket("Debt", debt)
            if b:
                buckets.append(b)

        # Gold
        gold = fund_picks.get("gold", []) or []
        if gold:
            b = _build_bucket("Gold", gold)
            if b:
                buckets.append(b)

        # Real Estate (REIT) — only if allocator put it in AND fund selector returned instruments
        reit = fund_picks.get("reit", []) or []
        if reit:
            b = _build_bucket("Real Estate", reit)
            if b:
                buckets.append(b)

        # Normalise bucket percentages to exactly 100 if AI drifted slightly
        total_pct = sum(b.percentage for b in buckets)
        if buckets and abs(total_pct - 100.0) > 0.5:
            scale = 100.0 / total_pct
            for b in buckets:
                b.percentage     = round(b.percentage * scale, 1)
                b.monthly_amount = round(monthly * b.percentage / 100, 2)

        return AllocationPlanResponse(
            monthly_invest_amount=float(monthly),
            currency="USD" if profile.tax_residency == "us" else "INR",
            buckets=buckets,
            rebalance_tip=allocation_data.get("rebalance_tip", ""),
            key_principles=allocation_data.get("key_principles", []),
            user_preferences_applied=user_preferences or None,
            disclaimer=_DISCLAIMER,
        )

    # ── Public entry point ─────────────────────────────────────────────────────

    async def create_plan(
        self,
        profile: InvestorProfile,
        india_candidates: list[dict] | None = None,
        us_candidates: list[dict] | None = None,
        user_preferences: dict[str, float] | None = None,
    ) -> AllocationPlanResponse:
        """Run 3 agents in parallel, then synthesize in Python."""
        india_cands = india_candidates or []
        us_cands    = us_candidates    or []

        # Phase 1: all three agents in parallel
        results = await asyncio.gather(
            self._pick_stocks(profile, india_cands, us_cands),
            self._select_funds(profile),
            self._determine_allocations(profile, user_preferences),
            return_exceptions=True,
        )

        stock_picks_or_exc, fund_picks_or_exc, allocation_or_exc = results

        # Stock picker failure is non-fatal — degrade gracefully to MFs only
        if isinstance(stock_picks_or_exc, Exception):
            log.warning("allocation_advisor.stock_picker_degraded", error=str(stock_picks_or_exc))
            stock_picks = {"india_picks": [], "us_picks": [], "skip_reason": "degraded"}
        else:
            stock_picks = stock_picks_or_exc

        # Fund selector or allocator failure is fatal
        if isinstance(fund_picks_or_exc, Exception):
            raise AIAgentError(f"Fund selector failed: {fund_picks_or_exc}") from fund_picks_or_exc
        if isinstance(allocation_or_exc, Exception):
            raise AIAgentError(f"Allocator failed: {allocation_or_exc}") from allocation_or_exc

        fund_picks    = fund_picks_or_exc
        allocation    = allocation_or_exc

        try:
            plan = self._synthesize_plan(profile, stock_picks, fund_picks, allocation, user_preferences)
        except (KeyError, ValueError, TypeError) as exc:
            log.error("allocation_advisor.synthesis_failed", error=str(exc))
            raise AIAgentError(f"Plan synthesis failed: {exc}") from exc

        log.info(
            "allocation_advisor.plan_created",
            buckets=len(plan.buckets),
            india_stocks=len(stock_picks.get("india_picks", [])),
            us_stocks=len(stock_picks.get("us_picks", [])),
            india_mfs=len(fund_picks.get("india_mfs", [])),
        )
        return plan
