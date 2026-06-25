from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import InvestorProfile, AllocationSlice


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_profile() -> InvestorProfile:
    return InvestorProfile(
        horizon_years=10,
        horizon_label="long",
        risk_tolerance="moderate",
        risk_capacity="high",
        emergency_fund_months=12,
        primary_goal="capital_appreciation",
        tax_residency="india",
        existing_allocation=[
            AllocationSlice(asset_class="India Equity", percentage=100.0),
        ],
        monthly_surplus=50000.0,
    )


# ── Investor Profile CRUD ──────────────────────────────────────────────────────

class TestInvestorProfile:
    def test_get_profile_404_when_not_set(self, client: TestClient) -> None:
        resp = client.get("/api/investor-profile")
        assert resp.status_code == 404

    def test_save_and_get_profile(self, client: TestClient, sample_profile: InvestorProfile) -> None:
        put = client.put(
            "/api/investor-profile",
            json=sample_profile.model_dump(mode="json"),
        )
        assert put.status_code == 200
        assert put.json()["horizon_years"] == 10

        get = client.get("/api/investor-profile")
        assert get.status_code == 200
        data = get.json()
        assert data["horizon_years"] == 10
        assert data["risk_tolerance"] == "moderate"
        assert data["tax_residency"] == "india"

    def test_update_profile_overwrites(self, client: TestClient, sample_profile: InvestorProfile) -> None:
        client.put("/api/investor-profile", json=sample_profile.model_dump(mode="json"))

        updated = sample_profile.model_copy(update={"horizon_years": 5, "horizon_label": "medium"})
        client.put("/api/investor-profile", json=updated.model_dump(mode="json"))

        get = client.get("/api/investor-profile")
        assert get.json()["horizon_years"] == 5


# ── Advisor Evaluate ───────────────────────────────────────────────────────────

class TestAdvisorEvaluate:
    def _save_profile(self, client: TestClient, sample_profile: InvestorProfile) -> None:
        client.put("/api/investor-profile", json=sample_profile.model_dump(mode="json"))

    def test_evaluate_404_without_profile(self, client: TestClient) -> None:
        resp = client.post("/api/advisor/evaluate", json={
            "asset_type": "stock",
            "ticker": "MSFT",
            "market": "us",
        })
        assert resp.status_code == 404

    def test_evaluate_stock_returns_recommendation(
        self, client: TestClient, sample_profile: InvestorProfile
    ) -> None:
        self._save_profile(client, sample_profile)
        resp = client.post("/api/advisor/evaluate", json={
            "asset_type": "stock",
            "ticker": "MSFT",
            "market": "us",
            "name": "Microsoft Corporation",
            "context": {
                "pe_ratio": 35.2,
                "roe": 0.45,
                "revenue_growth_yoy": 0.18,
                "valuation_classification": "fairly_valued",
                "sector": "Technology",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "MSFT"
        assert data["asset_type"] == "stock"
        assert data["profile_horizon_years"] == 10
        rec = data["recommendation"]
        assert rec["verdict"] in ("buy", "pass", "conditional")
        assert rec["confidence"] in ("high", "medium", "low")
        assert 0 <= rec["investor_match_score"] <= 100
        assert isinstance(rec["reasons_for"], list)
        assert isinstance(rec["reasons_against"], list)
        assert rec["summary"]

    def test_evaluate_fund_returns_recommendation(
        self, client: TestClient, sample_profile: InvestorProfile
    ) -> None:
        self._save_profile(client, sample_profile)
        resp = client.post("/api/advisor/evaluate", json={
            "asset_type": "fund",
            "ticker": "119598",
            "market": "india",
            "name": "Parag Parikh Flexi Cap Fund",
            "context": {
                "category": "Flexi Cap",
                "returns_3y_cagr": 22.1,
                "sharpe": 1.8,
                "is_closet_index": False,
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_type"] == "fund"

    def test_evaluate_cached_second_call(
        self, client: TestClient, sample_profile: InvestorProfile
    ) -> None:
        self._save_profile(client, sample_profile)
        payload = {
            "asset_type": "stock",
            "ticker": "NVDA",
            "market": "us",
            "context": {},
        }
        resp1 = client.post("/api/advisor/evaluate", json=payload)
        resp2 = client.post("/api/advisor/evaluate", json=payload)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["from_cache"] is True
