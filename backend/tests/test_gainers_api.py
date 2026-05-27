from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import (
    GainerDetail,
    GainersListResponse,
    MarketSummary,
    StockGainer,
)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["ai"] == "mock"
        assert body["cache"] == "memory"


class TestListGainers:
    def test_us_gainers_returns_200(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["market"] == "us"

    def test_india_market_accepted(self, client: TestClient) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/gainers/india?refresh=true")
        assert resp.status_code == 200
        assert resp.json()["market"] == "india"

    def test_invalid_market_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/gainers/europe")
        assert resp.status_code == 422

    def test_list_includes_summary_from_mock_ai(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        """
        With MOCK_AI=true the MarketAnalystAgent returns a mock MarketSummary.
        The response should include the summary field with all expected keys.
        """
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summary"] is not None
        summary = body["summary"]
        assert "narrative" in summary
        assert "themes" in summary
        assert "sentiment" in summary
        assert "watch_list" in summary
        assert "watch_reason" in summary
        # Validate sentiment is one of the allowed values
        valid_sentiments = {"very_bullish", "bullish", "mixed", "bearish", "very_bearish"}
        assert summary["sentiment"] in valid_sentiments

    def test_list_gainers_response_schema_is_valid(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        """Validate that the full response body can be parsed into GainersListResponse."""
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        body = resp.json()
        # Pydantic should be able to parse the response without error
        parsed = GainersListResponse(**body)
        assert parsed.market == "us"

    def test_gainers_have_quality_score_when_set(self, client: TestClient) -> None:
        """
        When market_data returns a gainer with quality_score and quality_label,
        those values should appear in the API response.
        """
        gainer_with_quality = StockGainer(
            ticker="NVDA",
            name="NVIDIA",
            market="us",
            price=950.0,
            change_pct=8.5,
            change_abs=74.5,
            volume=45_000_000,
            quality_score=9.2,
            quality_label="Strong",
        )
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[gainer_with_quality]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        assert resp.status_code == 200
        gainers = resp.json()["gainers"]
        assert len(gainers) == 1
        assert gainers[0]["quality_score"] == 9.2
        assert gainers[0]["quality_label"] == "Strong"

    def test_gainers_quality_label_is_valid_value(self, client: TestClient) -> None:
        gainer = StockGainer(
            ticker="AMD",
            name="AMD",
            market="us",
            price=150.0,
            change_pct=5.0,
            change_abs=7.5,
            volume=5_000_000,
            quality_score=7.2,
            quality_label="Moderate",
        )
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        gainers = resp.json()["gainers"]
        valid_labels = {"Strong", "Moderate", "Watch", "Risky"}
        assert gainers[0]["quality_label"] in valid_labels

    def test_cached_response_returns_from_cache_true(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            # First call — populates cache
            client.get("/api/gainers/us?refresh=true")
            # Second call — should come from cache
            resp = client.get("/api/gainers/us")
        assert resp.json()["from_cache"] is True

    def test_refresh_bypasses_cache(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        mock_fn = AsyncMock(return_value=[sample_us_gainer])
        with patch("services.market_data.MarketDataService.get_gainers", new=mock_fn):
            client.get("/api/gainers/us")           # Populate cache
            client.get("/api/gainers/us?refresh=true")  # Should call real service again

        # Called at least twice (once for populate, once for refresh)
        assert mock_fn.call_count >= 2


class TestGainerDetail:
    def test_detail_with_mock_ai_returns_full_response(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
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
        assert body["gainer"]["ticker"] == "NVDA"
        assert body["analysis"] is not None
        assert body["prediction"] is not None

    def test_detail_analysis_includes_related_beneficiaries(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        """
        Mock AI GainerAnalyst always returns related_beneficiaries.
        They must appear in the response JSON under analysis.
        """
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
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
        analysis = resp.json()["analysis"]
        assert "related_beneficiaries" in analysis
        assert isinstance(analysis["related_beneficiaries"], list)
        # Mock AI always returns AMD, SMCI, AVGO
        assert len(analysis["related_beneficiaries"]) > 0

    def test_detail_analysis_includes_beneficiary_reasoning(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
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
        analysis = resp.json()["analysis"]
        assert analysis.get("beneficiary_reasoning") is not None
        assert len(analysis["beneficiary_reasoning"]) > 10

    def test_unknown_ticker_returns_404(self, client: TestClient) -> None:
        with patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=None)):
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
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
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
        body = resp.json()
        assert body["status"] == "invalidated"
        assert "NVDA" in body["key"]

    def test_detail_response_schema_is_valid(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        """Full response body should parse into GainerDetail without error."""
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
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
        body = resp.json()
        parsed = GainerDetail(**body)
        assert parsed.gainer.ticker == "NVDA"

    def test_fundamentals_failure_returns_partial_result(
        self, client: TestClient, sample_us_gainer: StockGainer, sample_news
    ) -> None:
        """If fundamentals fail, the route should still return analysis (no prediction)."""
        from core.exceptions import MarketDataError

        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
            patch(
                "services.market_data.MarketDataService.get_fundamentals",
                new=AsyncMock(side_effect=MarketDataError("yfinance timeout")),
            ),
            patch(
                "services.news_fetcher.NewsFetcher.get_news",
                new=AsyncMock(return_value=sample_news),
            ),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        # Should succeed — partial result rather than 500
        assert resp.status_code == 200
        body = resp.json()
        assert body["fundamentals"] is None   # Failed
        assert body["analysis"] is not None   # Succeeded (no fundamentals needed)
        assert body["prediction"] is None     # Skipped (needs fundamentals)

    def test_news_failure_returns_partial_result(
        self, client: TestClient, sample_us_gainer: StockGainer, sample_fundamentals
    ) -> None:
        """If news fetch fails, route still returns analysis with empty news."""
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_us_gainer)),
            patch(
                "services.market_data.MarketDataService.get_fundamentals",
                new=AsyncMock(return_value=sample_fundamentals),
            ),
            patch(
                "services.news_fetcher.NewsFetcher.get_news",
                new=AsyncMock(side_effect=RuntimeError("News API down")),
            ),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        assert resp.status_code == 200
        body = resp.json()
        assert body["news"] == []
        assert body["analysis"] is not None

    def test_india_ticker_lookup(
        self,
        client: TestClient,
        sample_india_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer", new=AsyncMock(return_value=sample_india_gainer)),
            patch(
                "services.market_data.MarketDataService.get_fundamentals",
                new=AsyncMock(return_value=sample_fundamentals),
            ),
            patch(
                "services.news_fetcher.NewsFetcher.get_news",
                new=AsyncMock(return_value=sample_news),
            ),
        ):
            resp = client.get("/api/gainers/india/RELIANCE")
        assert resp.status_code == 200
        assert resp.json()["gainer"]["market"] == "india"
