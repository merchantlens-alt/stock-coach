"""Tests for GET /api/advisor/allocation-plan."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import (
    AllocationBucket,
    AllocationInstrument,
    AllocationPlanResponse,
    InvestorProfile,
)


@pytest.fixture
def sample_profile() -> InvestorProfile:
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
def sample_plan() -> AllocationPlanResponse:
    return AllocationPlanResponse(
        monthly_invest_amount=50_000.0,
        currency="INR",
        buckets=[
            AllocationBucket(
                asset_class="India Equity",
                percentage=50.0,
                monthly_amount=25_000.0,
                rationale="Core growth engine for your 10-year horizon.",
                instruments=[
                    AllocationInstrument(
                        name="HDFC Flexi Cap Fund",
                        instrument_type="mutual_fund",
                        weight_pct=60.0,
                        why="All-weather core allocation with consistent alpha",
                    ),
                    AllocationInstrument(
                        name="Mirae Asset Large Cap Fund",
                        instrument_type="mutual_fund",
                        weight_pct=40.0,
                        why="Stability anchor in large cap space",
                    ),
                ],
            ),
            AllocationBucket(
                asset_class="US Equity",
                percentage=20.0,
                monthly_amount=10_000.0,
                rationale="Dollar diversification via India-domiciled fund.",
                instruments=[
                    AllocationInstrument(
                        name="Motilal Oswal Nasdaq 100 ETF",
                        instrument_type="etf",
                        weight_pct=100.0,
                        why="Cost-efficient US tech exposure without LRS paperwork",
                    ),
                ],
            ),
            AllocationBucket(
                asset_class="Debt",
                percentage=20.0,
                monthly_amount=10_000.0,
                rationale="Stability buffer and rebalancing reservoir.",
                instruments=[
                    AllocationInstrument(
                        name="HDFC Short Duration Fund",
                        instrument_type="mutual_fund",
                        weight_pct=100.0,
                        why="Low volatility, liquid, expected 7-8% returns",
                    ),
                ],
            ),
            AllocationBucket(
                asset_class="Gold",
                percentage=10.0,
                monthly_amount=5_000.0,
                rationale="Inflation hedge; SGB gives tax-free return at maturity.",
                instruments=[
                    AllocationInstrument(
                        name="Sovereign Gold Bond (SGB)",
                        instrument_type="gold",
                        weight_pct=100.0,
                        why="2.5% interest + gold appreciation + tax-free at maturity",
                    ),
                ],
            ),
        ],
        rebalance_tip="Rebalance annually or when any class drifts more than 5% from target.",
        key_principles=[
            "Time in market beats timing the market — stay invested through corrections",
            "Review allocation when income or risk profile changes significantly",
        ],
        disclaimer="AI-generated guidance, not SEBI-registered advice.",
    )


class TestAllocationPlan:
    def test_no_profile_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/advisor/allocation-plan")
        assert resp.status_code == 404

    def test_profile_without_monthly_amount_returns_422(
        self, client: TestClient, sample_profile: InvestorProfile
    ) -> None:
        sample_profile.monthly_invest_amount = None
        with patch(
            "services.investor_profile_store.InvestorProfileStore.get",
            new=AsyncMock(return_value=sample_profile),
        ):
            resp = client.get("/api/advisor/allocation-plan")
        assert resp.status_code == 422

    def test_returns_plan_from_ai(
        self,
        client: TestClient,
        sample_profile: InvestorProfile,
        sample_plan: AllocationPlanResponse,
    ) -> None:
        with (
            patch(
                "services.investor_profile_store.InvestorProfileStore.get",
                new=AsyncMock(return_value=sample_profile),
            ),
            patch(
                "services.market_data.MarketDataService.get_gainers",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "agents.allocation_advisor_agent.AllocationAdvisorAgent.create_plan",
                new=AsyncMock(return_value=sample_plan),
            ),
        ):
            resp = client.get("/api/advisor/allocation-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_invest_amount"] == 50_000.0
        assert data["currency"] == "INR"
        assert len(data["buckets"]) == 4
        assert data["buckets"][0]["asset_class"] == "India Equity"
        assert data["buckets"][0]["percentage"] == 50.0
        assert len(data["buckets"][0]["instruments"]) == 2
        assert not data["from_cache"]

    def test_returns_cached_plan(
        self,
        client: TestClient,
        sample_profile: InvestorProfile,
        sample_plan: AllocationPlanResponse,
    ) -> None:
        cached_data = sample_plan.model_dump(mode="json")
        with (
            patch(
                "services.investor_profile_store.InvestorProfileStore.get",
                new=AsyncMock(return_value=sample_profile),
            ),
            patch(
                "services.cache.InMemoryCache.get",
                new=AsyncMock(return_value=cached_data),
            ),
        ):
            resp = client.get("/api/advisor/allocation-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["from_cache"] is True
        assert data["buckets"][0]["asset_class"] == "India Equity"

    def test_ai_failure_returns_503(
        self,
        client: TestClient,
        sample_profile: InvestorProfile,
    ) -> None:
        from core.exceptions import AIAgentError

        with (
            patch(
                "services.investor_profile_store.InvestorProfileStore.get",
                new=AsyncMock(return_value=sample_profile),
            ),
            patch(
                "services.market_data.MarketDataService.get_gainers",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "agents.allocation_advisor_agent.AllocationAdvisorAgent.create_plan",
                new=AsyncMock(side_effect=AIAgentError("Gemini timeout")),
            ),
        ):
            resp = client.get("/api/advisor/allocation-plan")

        assert resp.status_code == 503

    def test_gainers_failure_does_not_block_plan(
        self,
        client: TestClient,
        sample_profile: InvestorProfile,
        sample_plan: AllocationPlanResponse,
    ) -> None:
        """A market data error should log a warning but not prevent plan generation."""
        from core.exceptions import MarketDataError

        with (
            patch(
                "services.investor_profile_store.InvestorProfileStore.get",
                new=AsyncMock(return_value=sample_profile),
            ),
            patch(
                "services.market_data.MarketDataService.get_gainers",
                new=AsyncMock(side_effect=MarketDataError("yfinance timeout")),
            ),
            patch(
                "agents.allocation_advisor_agent.AllocationAdvisorAgent.create_plan",
                new=AsyncMock(return_value=sample_plan),
            ),
        ):
            resp = client.get("/api/advisor/allocation-plan")

        assert resp.status_code == 200
        assert not resp.json()["from_cache"]
