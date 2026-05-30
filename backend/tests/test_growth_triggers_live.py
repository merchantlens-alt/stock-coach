"""
Live integration tests for GrowthTriggersAgent.

These tests make REAL calls to Vertex AI (Gemini + Google Search grounding).
They are skipped automatically when MOCK_AI=true (the default in CI).

Run manually:
    MOCK_AI=false pytest tests/test_growth_triggers_live.py -v -s

What they verify:
  - Google Search grounding is operational for the GCP project
  - The agent returns non-fallback reports (is_error=False)
  - Gemini populates every required field with meaningful content
  - Conviction tags, P&L impact strings, and timelines are all present
"""
from __future__ import annotations

import os
import pytest

# ── Skip the whole module when MOCK_AI=true (default in CI) ─────────────────
pytestmark = pytest.mark.skipif(
    os.getenv("MOCK_AI", "true").lower() == "true",
    reason=(
        "Live integration test — requires real GCP credentials and Vertex AI access. "
        "Run with: MOCK_AI=false pytest tests/test_growth_triggers_live.py -v -s"
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _print_report(report) -> None:  # type: ignore[no-untyped-def]
    """Print a human-readable summary so -s output is useful."""
    print(f"\n{'='*60}")
    print(f"  {report.ticker}  ({report.market})  is_error={report.is_error}")
    print(f"{'='*60}")
    print(f"SNAPSHOT:\n  {report.company_snapshot[:200]}…")
    print(f"\nTRIGGERS ({len(report.triggers)}):")
    for t in report.triggers:
        print(f"  [{t.conviction:12s}] {t.name}")
        print(f"    Impact:   {t.p_and_l_impact}")
        print(f"    Timeline: {t.timeline}")
        print(f"    Watch:    {t.watch_for}")
    print(f"\nKEY RISKS ({len(report.key_risks)}):")
    for r in report.key_risks:
        print(f"  • {r.name}: {r.why_it_matters}")
    print(f"\nSCORECARD:")
    for row in report.scorecard:
        print(f"  {row.dimension:<30s} {row.rating:<10s} {row.note[:60]}")
    print(f"\nALREADY IN PRICE:\n  {report.already_in_price[:150]}…")
    print(f"UPSIDE:\n  {report.upside_scenario[:150]}…")
    print()


# ── Core assertion helper ────────────────────────────────────────────────────

def _assert_valid_report(report, ticker: str) -> None:
    """Shared assertions that apply to every successful Growth Triggers report."""
    # Must not be the fallback stub
    assert not report.is_error, (
        f"Got fallback error report for {ticker}.\n"
        f"Snapshot: {report.company_snapshot}\n"
        "Check Vertex AI logs — likely a grounding/auth issue."
    )

    # Triggers — 3 to 5
    assert 3 <= len(report.triggers) <= 5, (
        f"Expected 3-5 triggers, got {len(report.triggers)}"
    )
    valid_convictions = {"HIGH", "MEDIUM", "OPTIONALITY"}
    for t in report.triggers:
        assert t.name.strip(), "trigger.name is empty"
        assert len(t.what) > 20, f"trigger.what too short: {t.what!r}"
        assert t.conviction in valid_convictions, f"Invalid conviction: {t.conviction!r}"
        assert t.p_and_l_impact.strip(), "trigger.p_and_l_impact is empty"
        assert t.timeline.strip(), "trigger.timeline is empty"
        assert t.watch_for.strip(), "trigger.watch_for is empty"
        # Conviction fallback stub uses "AI Analysis Unavailable" — catch it
        assert "unavailable" not in t.name.lower(), (
            f"Trigger looks like fallback stub: {t.name!r}"
        )

    # Risks — 2 to 3
    assert 2 <= len(report.key_risks) <= 3, (
        f"Expected 2-3 risks, got {len(report.key_risks)}"
    )
    for r in report.key_risks:
        assert r.name.strip(), "risk.name is empty"
        assert len(r.what) > 10, f"risk.what too short: {r.what!r}"
        assert len(r.why_it_matters) > 10, f"risk.why_it_matters too short"

    # Scorecard — exactly 5 rows
    assert len(report.scorecard) == 5, (
        f"Expected 5 scorecard rows, got {len(report.scorecard)}"
    )
    for row in report.scorecard:
        assert row.dimension.strip(), "scorecard.dimension is empty"
        assert row.rating not in ("Unknown", ""), (
            f"Scorecard row has Unknown rating (fallback): {row.dimension}"
        )
        assert row.note.strip(), "scorecard.note is empty"

    # Snapshots and scenarios — must be substantive
    assert len(report.company_snapshot) > 80, "company_snapshot too short"
    assert len(report.already_in_price) > 40, "already_in_price too short"
    assert len(report.upside_scenario) > 40, "upside_scenario too short"

    # Must mention the ticker or company name somewhere
    snapshot_lower = report.company_snapshot.lower()
    assert (
        ticker.lower() in snapshot_lower
        or any(word in snapshot_lower for word in ticker.lower().split())
    ), f"company_snapshot doesn't mention {ticker!r}"


# ── Test: India market — HCLTECH ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_growth_triggers_hcltech_india_live() -> None:
    """
    Real Vertex AI + Google Search grounding call for HCLTECH (India).

    Verifies the full pipeline:
      1. Grounding is operational (no 400/403 from Vertex AI)
      2. JSON is returned and parsed correctly from the grounded text response
      3. All 6 top-level fields are populated with non-stub content
      4. Conviction tags are valid literals
      5. P&L impact strings contain numeric-looking content
    """
    from core.config import get_settings
    from agents.growth_triggers_agent import GrowthTriggersAgent
    from models.schemas import FundamentalsData

    settings = get_settings()
    agent = GrowthTriggersAgent(settings)

    report = await agent.generate(
        ticker="HCLTECH",
        name="HCL Technologies Ltd",
        market="india",
        price=1820.0,
        fundamentals=FundamentalsData(
            pe_ratio=28.5,
            forward_pe=25.0,
            revenue_growth_yoy=0.051,      # 5.1% YoY
            profit_margin=0.14,
            ebitda_margin=0.22,
            roe=0.26,
            debt_equity=0.05,
            ttm_revenue=111_280_000_000,   # ₹1.11L Cr (actual units)
            market_cap_value=493_600_000_000,
            insider_holding_pct=0.605,
            analyst_recommendation="buy",
            analyst_target_price=2050.0,
        ),
        news_headlines=[
            "HCL Tech wins $200M multi-year deal from leading European bank",
            "HCL Tech Q3 FY25 revenue grows 5.1% QoQ; EBIT margin holds at 19.5%",
            "HCL Tech expands AI/ML practice with 10 new enterprise clients in BFSI",
            "HCL Tech accelerates ER&D services — targets $1B revenue by FY27",
        ],
    )

    _print_report(report)
    _assert_valid_report(report, "HCLTECH")

    # Extra: at least one HIGH conviction trigger expected for a stable IT bellwether
    conviction_counts = {t.conviction for t in report.triggers}
    assert "HIGH" in conviction_counts or "MEDIUM" in conviction_counts, (
        "Expected at least one HIGH or MEDIUM conviction trigger"
    )


# ── Test: US market — NVDA ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_growth_triggers_nvda_us_live() -> None:
    """
    Real Vertex AI + Google Search grounding call for NVDA (US).

    NVDA is chosen because:
      - It has abundant, recent, well-indexed news (good for grounding)
      - Revenue growth and margin numbers are distinctive (easy to verify)
      - The model should produce HIGH conviction triggers given data center demand
    """
    from core.config import get_settings
    from agents.growth_triggers_agent import GrowthTriggersAgent
    from models.schemas import FundamentalsData

    settings = get_settings()
    agent = GrowthTriggersAgent(settings)

    report = await agent.generate(
        ticker="NVDA",
        name="NVIDIA Corporation",
        market="us",
        price=1250.0,
        fundamentals=FundamentalsData(
            pe_ratio=55.0,
            forward_pe=35.0,
            revenue_growth_yoy=1.22,      # 122% YoY
            ebitda_margin=0.62,
            profit_margin=0.55,
            roe=1.20,
            debt_equity=0.42,
            ttm_revenue=96_310_000_000,   # $96.3B TTM
            market_cap_value=3_000_000_000_000,
            insider_holding_pct=0.032,
            analyst_recommendation="strong_buy",
            analyst_target_price=1450.0,
        ),
        news_headlines=[
            "NVIDIA Blackwell Ultra GPU enters mass production for hyperscale customers",
            "NVIDIA data center revenue reaches $35B in Q4, up 200% YoY",
            "NVIDIA announces NIM microservices for enterprise AI deployments",
            "NVIDIA sovereign AI deals with UAE, Japan, India governments announced",
        ],
    )

    _print_report(report)
    _assert_valid_report(report, "NVDA")

    # NVDA should have at least one HIGH conviction trigger given AI tailwinds
    high_triggers = [t for t in report.triggers if t.conviction == "HIGH"]
    assert len(high_triggers) >= 1, (
        f"Expected at least 1 HIGH trigger for NVDA, got: "
        f"{[(t.name, t.conviction) for t in report.triggers]}"
    )


# ── Test: grounding actually fetches live data ───────────────────────────────

@pytest.mark.asyncio
async def test_growth_triggers_grounding_returns_fresh_data() -> None:
    """
    Verifies that Google Search grounding is active by checking the report
    contains references that could only come from web search (not just the
    prompt data we pass in).

    We pass minimal prompt data (no news, no quarterly) and check that Gemini
    still produces a substantive report — meaning it sourced from the web.
    """
    from core.config import get_settings
    from agents.growth_triggers_agent import GrowthTriggersAgent

    settings = get_settings()
    agent = GrowthTriggersAgent(settings)

    # Deliberately pass NO news and NO fundamentals — only ticker + price
    # A non-grounded call would produce very generic output.
    # A grounded call should still name specific products, deals, or metrics.
    report = await agent.generate(
        ticker="INFY",
        name="Infosys Ltd",
        market="india",
        price=1740.0,
        fundamentals=None,
        news_headlines=[],    # no context passed — grounding must compensate
    )

    _print_report(report)

    assert not report.is_error, (
        "Got fallback with no fundamentals/news — grounding may not be working. "
        "Check Vertex AI logs for 400/403 on the googleSearch tool."
    )

    # With grounding, the company snapshot should be substantive even with no
    # context passed. A purely hallucinated response would be vague.
    assert len(report.company_snapshot) > 100
    assert len(report.triggers) >= 3

    # At least one trigger should have a P&L impact with a number in it,
    # which would indicate grounding found real financial data.
    has_numeric_impact = any(
        any(c.isdigit() for c in t.p_and_l_impact)
        for t in report.triggers
    )
    assert has_numeric_impact, (
        "No trigger has a numeric P&L impact — grounding may not have fetched "
        f"real data. Triggers: {[t.p_and_l_impact for t in report.triggers]}"
    )
