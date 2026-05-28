from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import (
    GainerDetail,
    GainersListResponse,
    MarketSummary,
    StockAnalysisResponse,
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
        valid_sentiments = {"very_bullish", "bullish", "mixed", "bearish", "very_bearish"}
        assert summary["sentiment"] in valid_sentiments

    def test_list_gainers_response_schema_is_valid(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        body = resp.json()
        parsed = GainersListResponse(**body)
        assert parsed.market == "us"

    def test_gainers_have_quality_score_when_set(self, client: TestClient) -> None:
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

    def test_gainers_have_signal_tier(self, client: TestClient) -> None:
        gainer = StockGainer(
            ticker="ASTC",
            name="Astrotech",
            market="us",
            price=6.55,
            change_pct=165.0,
            change_abs=4.08,
            volume=500_000,
            signal_tier="confirmed",
        )
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[gainer]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        gainers = resp.json()["gainers"]
        assert gainers[0]["signal_tier"] == "confirmed"

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
            client.get("/api/gainers/us?refresh=true")
            resp = client.get("/api/gainers/us")
        assert resp.json()["from_cache"] is True

    def test_refresh_bypasses_cache(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        mock_fn = AsyncMock(return_value=[sample_us_gainer])
        with patch("services.market_data.MarketDataService.get_gainers", new=mock_fn):
            client.get("/api/gainers/us")
            client.get("/api/gainers/us?refresh=true")
        assert mock_fn.call_count >= 2

    def test_empty_result_serves_last_known_good(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        """If Gemini returns [] but LKG exists, show LKG rather than a blank page."""
        # First request succeeds — populates LKG
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[sample_us_gainer]),
        ):
            client.get("/api/gainers/us?refresh=true")

        # Second request returns empty (market closed / Gemini glitch)
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")

        body = resp.json()
        assert resp.status_code == 200
        assert len(body["gainers"]) > 0          # LKG served, not blank
        assert body["from_cache"] is True

    def test_empty_result_no_lkg_returns_empty_list(
        self, client: TestClient
    ) -> None:
        """If no LKG exists and Gemini returns empty, return graceful empty response."""
        with patch(
            "services.market_data.MarketDataService.get_gainers",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/gainers/us?refresh=true")
        assert resp.status_code == 200
        assert resp.json()["gainers"] == []

    def test_market_aware_ttl_used_outside_hours(
        self, client: TestClient, sample_us_gainer: StockGainer
    ) -> None:
        """Outside market hours, _gainers_ttl returns 24 h for the 1d period."""
        from api.routes.gainers import _gainers_ttl
        from unittest.mock import patch as _patch
        from core.config import get_settings

        settings = get_settings()
        with _patch("api.routes.gainers._is_market_hours", return_value=False):
            ttl = _gainers_ttl("us", "1d", settings)
        assert ttl == 24 * 3600

    def test_market_aware_ttl_used_during_hours(self, client: TestClient) -> None:
        """During market hours, _gainers_ttl returns gainers_list_ttl for 1d."""
        from api.routes.gainers import _gainers_ttl
        from unittest.mock import patch as _patch
        from core.config import get_settings

        settings = get_settings()
        with _patch("api.routes.gainers._is_market_hours", return_value=True):
            ttl = _gainers_ttl("us", "1d", settings)
        assert ttl == settings.gainers_list_ttl

    def test_weekly_ttl_is_always_24h(self, client: TestClient) -> None:
        """1w period always uses 24 h regardless of market hours."""
        from api.routes.gainers import _gainers_ttl
        from core.config import get_settings

        settings = get_settings()
        assert _gainers_ttl("us", "1w", settings) == 24 * 3600

    def test_monthly_ttl_is_always_48h(self, client: TestClient) -> None:
        """1m period always uses 48 h regardless of market hours."""
        from api.routes.gainers import _gainers_ttl
        from core.config import get_settings

        settings = get_settings()
        assert _gainers_ttl("us", "1m", settings) == 48 * 3600


class TestGainerDetail:
    """Tests for GET /gainers/{market}/{ticker} — fast data endpoint (no AI)."""

    def test_detail_returns_gainer_fundamentals_news(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        assert resp.status_code == 200
        body = resp.json()
        assert body["gainer"]["ticker"] == "NVDA"
        assert body["fundamentals"] is not None
        assert len(body["news"]) > 0
        # analysis and prediction are NOT in the fast endpoint
        assert "analysis" not in body
        assert "prediction" not in body

    def test_detail_response_schema_is_valid(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        body = resp.json()
        parsed = GainerDetail(**body)
        assert parsed.gainer.ticker == "NVDA"

    def test_unknown_ticker_returns_404(self, client: TestClient) -> None:
        with patch("api.routes.gainers._resolve_gainer",
                   new=AsyncMock(return_value=(None, {}))):
            resp = client.get("/api/gainers/us/FAKEXYZ999")
        assert resp.status_code == 404

    def test_detail_cached_on_second_call(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp1 = client.get("/api/gainers/us/NVDA")
            assert resp1.status_code == 200
            assert not resp1.json()["from_cache"]

            resp2 = client.get("/api/gainers/us/NVDA")
            assert resp2.status_code == 200
            assert resp2.json()["from_cache"]

    def test_fundamentals_failure_returns_partial_result(
        self, client: TestClient, sample_us_gainer: StockGainer, sample_news
    ) -> None:
        from core.exceptions import MarketDataError

        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(side_effect=MarketDataError("yfinance timeout"))),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        assert resp.status_code == 200
        body = resp.json()
        assert body["fundamentals"] is None       # failed → null
        assert body["gainer"]["ticker"] == "NVDA" # gainer always present

    def test_news_failure_returns_partial_result(
        self, client: TestClient, sample_us_gainer: StockGainer, sample_fundamentals
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(side_effect=RuntimeError("News API down"))),
        ):
            resp = client.get("/api/gainers/us/NVDA")
        assert resp.status_code == 200
        body = resp.json()
        assert body["news"] == []
        assert body["fundamentals"] is not None

    def test_india_ticker_lookup(
        self,
        client: TestClient,
        sample_india_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_india_gainer, {}))),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/india/RELIANCE")
        assert resp.status_code == 200
        assert resp.json()["gainer"]["market"] == "india"

    def test_cache_invalidation_endpoint(self, client: TestClient) -> None:
        resp = client.delete("/api/gainers/us/NVDA/cache")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "invalidated"
        assert body["ticker"] == "NVDA"


class TestGainerAnalyse:
    """Tests for GET /gainers/{market}/{ticker}/analyse — slow AI endpoint."""

    def test_analyse_returns_analysis_and_prediction(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("api.routes.gainers._safe_get_gainers",
                  new=AsyncMock(return_value=[sample_us_gainer])),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA/analyse")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ticker"] == "NVDA"
        assert body["analysis"] is not None
        assert body["prediction"] is not None

    def test_analyse_response_schema_is_valid(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("api.routes.gainers._safe_get_gainers",
                  new=AsyncMock(return_value=[sample_us_gainer])),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA/analyse")
        body = resp.json()
        parsed = StockAnalysisResponse(**body)
        assert parsed.ticker == "NVDA"
        assert parsed.analysis is not None

    def test_analyse_includes_related_beneficiaries(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("api.routes.gainers._safe_get_gainers",
                  new=AsyncMock(return_value=[sample_us_gainer])),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp = client.get("/api/gainers/us/NVDA/analyse")
        analysis = resp.json()["analysis"]
        assert "related_beneficiaries" in analysis
        assert isinstance(analysis["related_beneficiaries"], list)
        assert len(analysis["related_beneficiaries"]) > 0

    def test_analyse_unknown_ticker_returns_404(self, client: TestClient) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(None, {}))),
            patch("api.routes.gainers._safe_get_gainers",
                  new=AsyncMock(return_value=[])),
        ):
            resp = client.get("/api/gainers/us/FAKEXYZ999/analyse")
        assert resp.status_code == 404

    def test_analyse_cached_on_second_call(
        self,
        client: TestClient,
        sample_us_gainer: StockGainer,
        sample_fundamentals,
        sample_news,
    ) -> None:
        with (
            patch("api.routes.gainers._resolve_gainer",
                  new=AsyncMock(return_value=(sample_us_gainer, {}))),
            patch("api.routes.gainers._safe_get_gainers",
                  new=AsyncMock(return_value=[sample_us_gainer])),
            patch("services.market_data.MarketDataService.get_fundamentals",
                  new=AsyncMock(return_value=sample_fundamentals)),
            patch("services.news_fetcher.NewsFetcher.get_news",
                  new=AsyncMock(return_value=sample_news)),
        ):
            resp1 = client.get("/api/gainers/us/NVDA/analyse")
            assert not resp1.json()["from_cache"]

            resp2 = client.get("/api/gainers/us/NVDA/analyse")
            assert resp2.json()["from_cache"]
