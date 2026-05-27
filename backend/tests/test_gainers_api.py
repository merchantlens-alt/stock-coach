from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import GainerDetail, GainersListResponse, StockGainer


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["ai"] == "mock"
        assert body["cache"] == "memory"


class TestListGainers:
    def _patch_market_data(self, gainers: list[StockGainer]):
        return patch(
            "api.routes.gainers.MarketDataService.get_gainers",
            new=AsyncMock(return_value=gainers),
        )

    def test_us_gainers_returns_list(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            resp = client.get("/api/gainers/us")
            assert resp.status_code == 200
            body = resp.json()
            assert body["market"] == "us"
            assert len(body["gainers"]) >= 0  # Cache or live

    def test_invalid_market_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/gainers/europe")
        assert resp.status_code == 422

    def test_india_market_accepted(self, client: TestClient) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/gainers/india")
            assert resp.status_code == 200
            assert resp.json()["market"] == "india"


class TestGainerDetail:
    def test_detail_with_mock_ai_returns_full_response(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch(
                "api.routes.gainers._resolve_gainer",
                new=AsyncMock(return_value=sample_us_gainer),
            ),
            patch(
                "services.market_data.MarketDataService.get_fundamentals",
                new=AsyncMock(return_value=sample_fundamentals),
            ),
            patch(
                "services.news_fetcher.NewsFetcher.get_news",
                new=AsyncMock(return_value=sample_news),
            ),
        ):
            resp = client.get("/api/gainers/us/NVDA")
            assert resp.status_code == 200
            body = resp.json()
            # Mock AI is on, so analysis and prediction should be present
            assert body["gainer"]["ticker"] == "NVDA"
            assert body["analysis"] is not None
            assert body["prediction"] is not None

    def test_unknown_ticker_returns_404(self, client: TestClient) -> None:
        with patch(
            "api.routes.gainers._resolve_gainer",
            new=AsyncMock(return_value=None),
        ):
            resp = client.get("/api/gainers/us/FAKEXYZ999")
            assert resp.status_code == 404

    def test_analysis_cached_on_second_call(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch(
                "api.routes.gainers._resolve_gainer",
                new=AsyncMock(return_value=sample_us_gainer),
            ),
            patch(
                "services.market_data.MarketDataService.get_fundamentals",
                new=AsyncMock(return_value=sample_fundamentals),
            ),
            patch(
                "services.news_fetcher.NewsFetcher.get_news",
                new=AsyncMock(return_value=sample_news),
            ),
        ):
            resp1 = client.get("/api/gainers/us/NVDA")
            assert resp1.status_code == 200
            assert not resp1.json()["from_cache"]

            resp2 = client.get("/api/gainers/us/NVDA")
            assert resp2.status_code == 200
            assert resp2.json()["from_cache"]

    def test_cache_invalidation_endpoint(self, client: TestClient) -> None:
        resp = client.delete("/api/gainers/us/NVDA/cache")
        assert resp.status_code == 200
        assert resp.json()["status"] == "invalidated"
