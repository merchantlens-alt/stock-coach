"""Unit tests for AllocationAdvisorAgent internals.

These bypass the FastAPI route and exercise the agent directly so the actual QARP
stock-picker prompt assembly and the Python synthesis (REIT single-source-of-truth)
are covered — the route-level tests stub create_plan and never touch these.
"""
from __future__ import annotations

import asyncio
import json

from unittest.mock import AsyncMock

import pytest

from agents.allocation_advisor_agent import AllocationAdvisorAgent
from core.config import get_settings
from models.schemas import InvestorProfile


@pytest.fixture
def agent() -> AllocationAdvisorAgent:
    return AllocationAdvisorAgent(get_settings())


@pytest.fixture
def moderate_profile() -> InvestorProfile:
    return InvestorProfile(
        horizon_years=10,
        horizon_label="long",
        risk_tolerance="moderate",
        risk_capacity="high",
        emergency_fund_months=6,
        primary_goal="capital_appreciation",
        tax_residency="india",
        age=32,
        monthly_invest_amount=50_000.0,
        existing_allocation=[],
    )


@pytest.fixture
def dip_candidate() -> dict:
    """A quality-on-dip candidate as emitted by the quality_dip_screener."""
    return {
        "ticker": "INFY.NS",
        "name": "Infosys Limited",
        "sector": "IT",
        "price": 1000.0,
        "pct_from_52w_high": -40.0,
        "fundamental_score": 6.3,
        "grade": "B",
        "dip_quality": 9.0,
        "composite_score": 7.4,
        "key_metrics": {"roe": "28%"},
        "warnings": [],
    }


class TestStockPickerDipSignal:
    """The picker must SEE the dip dimension — otherwise the QARP thesis dies here."""

    def test_dip_fields_reach_picker_prompt(self, agent, moderate_profile, dip_candidate) -> None:
        captured: dict = {}

        async def fake_gemini(messages, system_prompt, temperature=0.15):
            captured["messages"] = messages
            captured["system_prompt"] = system_prompt
            return json.dumps({"india_picks": [], "us_picks": [], "skip_reason": None})

        agent._call_gemini = AsyncMock(side_effect=fake_gemini)  # type: ignore[method-assign]
        asyncio.run(agent._pick_stocks(moderate_profile, [dip_candidate], []))

        user_text = captured["messages"][0]["parts"][0]["text"]
        assert "dip=-40%" in user_text
        assert "dip_quality=9.0/10" in user_text
        assert "composite=7.4" in user_text

    def test_picker_system_prompt_is_qarp_not_pure_quality(self, agent) -> None:
        from agents.allocation_advisor_agent import _STOCK_PICKER_SYSTEM

        sp = _STOCK_PICKER_SYSTEM.lower()
        # The ranking edge must be the composite (quality x dip), not fundamental_score alone
        assert "composite" in sp
        assert "52-week high" in _STOCK_PICKER_SYSTEM
        # Quality floor aligned with the screener's 5.5 filter, not the old 6.0
        assert "5.5" in _STOCK_PICKER_SYSTEM
        assert "6.0" not in _STOCK_PICKER_SYSTEM

    def test_picker_failure_is_non_fatal(self, agent, moderate_profile, dip_candidate) -> None:
        agent._call_gemini = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        result = asyncio.run(agent._pick_stocks(moderate_profile, [dip_candidate], []))
        assert result["india_picks"] == []
        assert result["us_picks"] == []
        assert result["skip_reason"]


class TestReitSingleSourceOfTruth:
    """The allocator is the sole gate for REIT inclusion; the fund selector only supplies the menu."""

    @staticmethod
    def _fund_picks() -> dict:
        return {
            "india_mfs": [{"name": "PPFAS Flexi Cap", "instrument_type": "mutual_fund", "weight_pct": 100, "why": "x"}],
            "us_instruments": [],
            "debt": [{"name": "HDFC Short Duration", "instrument_type": "mutual_fund", "weight_pct": 100, "why": "x"}],
            "gold": [{"name": "SBI Gold ETF", "instrument_type": "gold", "weight_pct": 100, "why": "x"}],
            "reit": [{"name": "Embassy Office Parks REIT", "instrument_type": "reit", "weight_pct": 100, "why": "x"}],
        }

    @staticmethod
    def _alloc(real_estate_pct: float) -> dict:
        india = 50.0 - real_estate_pct
        return {
            "allocations": {"India Equity": india, "Debt": 30, "Gold": 20, "Real Estate": real_estate_pct},
            "rationales": {},
            "rebalance_tip": "",
            "key_principles": [],
        }

    def test_reit_dropped_when_allocator_gives_zero(self, agent, moderate_profile) -> None:
        plan = agent._synthesize_plan(
            moderate_profile,
            {"india_picks": [], "us_picks": []},
            self._fund_picks(),
            self._alloc(0),
            None,
        )
        assert not any(b.asset_class == "Real Estate" for b in plan.buckets)
        assert abs(sum(b.percentage for b in plan.buckets) - 100.0) < 0.5

    def test_reit_present_when_allocator_gives_weight(self, agent, moderate_profile) -> None:
        plan = agent._synthesize_plan(
            moderate_profile,
            {"india_picks": [], "us_picks": []},
            self._fund_picks(),
            self._alloc(5),
            None,
        )
        reit_buckets = [b for b in plan.buckets if b.asset_class == "Real Estate"]
        assert len(reit_buckets) == 1
        assert reit_buckets[0].instruments[0].instrument_type == "reit"
        assert abs(sum(b.percentage for b in plan.buckets) - 100.0) < 0.5
