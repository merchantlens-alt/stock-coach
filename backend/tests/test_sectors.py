"""Tests for the sector scanner endpoint and service."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import SectorInfo, SectorScanResponse, SectorStock


def _make_sector_response(market: str = "india") -> SectorScanResponse:
    return SectorScanResponse(
        market=market,  # type: ignore[arg-type]
        sectors=[
            SectorInfo(
                name="Information Technology & SaaS",
                rank=1,
                sort_score=92,
                cyclicality="low",
                growth_tag="High Growth",
                macro_theme="AI services exports",
                top_stocks=[
                    SectorStock(
                        ticker="TCS.NS",
                        name="Tata Consultancy Services",
                        price=3850.0,
                        change_1yr_pct=12.5,
                        change_6m_pct=5.1,
                        pe_ratio=28.5,
                        market_cap_cr=1400000.0,
                    ),
                    SectorStock(
                        ticker="INFY.NS",
                        name="Infosys Ltd",
                        price=1750.0,
                        change_1yr_pct=8.2,
                    ),
                ],
            ),
            SectorInfo(
                name="Metals & Mining",
                rank=22,
                sort_score=40,
                cyclicality="high",
                growth_tag="Cyclical",
                macro_theme="China demand overhang",
                top_stocks=[],
            ),
        ],
        from_cache=False,
    )


class TestSectorsEndpoint:
    def test_india_sectors_returns_200(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("india")
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            resp = client.get("/api/sectors/india")
        assert resp.status_code == 200
        data = resp.json()
        assert data["market"] == "india"
        assert len(data["sectors"]) == 2

    def test_us_sectors_returns_200(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("us")
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            resp = client.get("/api/sectors/us")
        assert resp.status_code == 200
        assert resp.json()["market"] == "us"

    def test_invalid_market_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/sectors/france")
        assert resp.status_code == 422

    def test_sector_fields_present(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("india")
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            data = client.get("/api/sectors/india").json()
        sector = data["sectors"][0]
        assert sector["name"] == "Information Technology & SaaS"
        assert sector["sort_score"] == 92
        assert sector["cyclicality"] == "low"
        assert sector["growth_tag"] == "High Growth"
        assert "macro_theme" in sector
        assert len(sector["top_stocks"]) == 2

    def test_top_stock_fields_present(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("india")
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            data = client.get("/api/sectors/india").json()
        stock = data["sectors"][0]["top_stocks"][0]
        assert stock["ticker"] == "TCS.NS"
        assert stock["price"] == 3850.0
        assert stock["change_1yr_pct"] == 12.5
        assert stock["pe_ratio"] == 28.5

    def test_refresh_param_passes_through(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("india")
        mock_fn = AsyncMock(return_value=mock_resp)
        with patch("api.routes.sectors.get_sector_scan", new=mock_fn):
            client.get("/api/sectors/india?refresh=true")
        mock_fn.assert_called_once()
        _args, kwargs = mock_fn.call_args
        assert kwargs.get("refresh") is True or _args[2] is True

    def test_requires_auth(self) -> None:
        from main import create_app
        unauthed = TestClient(create_app())
        resp = unauthed.get("/api/sectors/india")
        assert resp.status_code == 401

    def test_from_cache_flag_propagated(self, client: TestClient) -> None:
        mock_resp = _make_sector_response("india")
        mock_resp.from_cache = True
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            data = client.get("/api/sectors/india").json()
        assert data["from_cache"] is True

    def test_empty_top_stocks_sector_included(self, client: TestClient) -> None:
        """Sectors with no fetched stock data should still appear in the list."""
        mock_resp = _make_sector_response("india")
        with patch(
            "api.routes.sectors.get_sector_scan",
            new=AsyncMock(return_value=mock_resp),
        ):
            data = client.get("/api/sectors/india").json()
        empty_sector = next(s for s in data["sectors"] if s["name"] == "Metals & Mining")
        assert empty_sector is not None
        assert empty_sector["top_stocks"] == []


class TestMultiAgentAllocationPlan:
    """Verify multi-agent plan still produces a valid AllocationPlanResponse."""

    def _profile_payload(self) -> dict:
        return {
            "horizon_years": 10,
            "horizon_label": "long",
            "risk_tolerance": "aggressive",
            "risk_capacity": "high",
            "emergency_fund_months": 6,
            "primary_goal": "capital_appreciation",
            "tax_residency": "india",
            "monthly_invest_amount": 50000,
            "existing_allocation": [],
        }

    def _mock_plan(self):
        from models.schemas import (
            AllocationBucket, AllocationInstrument, AllocationPlanResponse,
        )
        return AllocationPlanResponse(
            monthly_invest_amount=50000,
            currency="INR",
            buckets=[
                AllocationBucket(
                    asset_class="India Equity",
                    percentage=55.0,
                    monthly_amount=27500.0,
                    rationale="Growth engine for 10yr horizon",
                    instruments=[
                        AllocationInstrument(
                            name="Parag Parikh Flexi Cap Fund",
                            instrument_type="mutual_fund",
                            weight_pct=70.0,
                            why="Flexi-cap with US exposure",
                        ),
                        AllocationInstrument(
                            name="TCS.NS",
                            instrument_type="stock",
                            weight_pct=30.0,
                            why="fundamental_score=8.5/10",
                        ),
                    ],
                ),
                AllocationBucket(
                    asset_class="Debt",
                    percentage=20.0,
                    monthly_amount=10000.0,
                    rationale="Safety net",
                    instruments=[
                        AllocationInstrument(
                            name="HDFC Short Duration Fund",
                            instrument_type="mutual_fund",
                            weight_pct=100.0,
                            why="AAA short duration",
                        )
                    ],
                ),
                AllocationBucket(
                    asset_class="Gold",
                    percentage=10.0,
                    monthly_amount=5000.0,
                    rationale="Insurance hedge",
                    instruments=[
                        AllocationInstrument(
                            name="Nippon India Gold ETF",
                            instrument_type="gold",
                            weight_pct=100.0,
                            why="Low expense ratio",
                        )
                    ],
                ),
                AllocationBucket(
                    asset_class="US Equity",
                    percentage=15.0,
                    monthly_amount=7500.0,
                    rationale="Global diversification",
                    instruments=[
                        AllocationInstrument(
                            name="Motilal Oswal Nasdaq 100 ETF",
                            instrument_type="etf",
                            weight_pct=100.0,
                            why="Low tracking error",
                        )
                    ],
                ),
            ],
            rebalance_tip="Rebalance annually",
            key_principles=["Stay invested", "Rebalance annually"],
            disclaimer="Educational only.",
        )

    def test_plan_endpoint_returns_200(self, client: TestClient) -> None:
        # Set up profile first
        client.put("/api/investor-profile", json=self._profile_payload())

        mock_plan = self._mock_plan()
        with patch(
            "services.fundamental_scoring.enrich_candidates_with_fundamentals",
            new=AsyncMock(side_effect=lambda cands, *a, **kw: cands),
        ), patch(
            "agents.allocation_advisor_agent.AllocationAdvisorAgent.create_plan",
            new=AsyncMock(return_value=mock_plan),
        ):
            resp = client.get("/api/advisor/allocation-plan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_invest_amount"] == 50000
        assert len(data["buckets"]) == 4

    def test_plan_buckets_structure(self, client: TestClient) -> None:
        client.put("/api/investor-profile", json=self._profile_payload())
        mock_plan = self._mock_plan()
        with patch(
            "services.fundamental_scoring.enrich_candidates_with_fundamentals",
            new=AsyncMock(side_effect=lambda cands, *a, **kw: cands),
        ), patch(
            "agents.allocation_advisor_agent.AllocationAdvisorAgent.create_plan",
            new=AsyncMock(return_value=mock_plan),
        ):
            data = client.get("/api/advisor/allocation-plan").json()
        india_bucket = next(b for b in data["buckets"] if b["asset_class"] == "India Equity")
        assert india_bucket["percentage"] == 55.0
        assert len(india_bucket["instruments"]) == 2
        instrument_names = [i["name"] for i in india_bucket["instruments"]]
        assert "Parag Parikh Flexi Cap Fund" in instrument_names
        assert "TCS.NS" in instrument_names
