"""
Tests for the Radar catalyst-scanner feature.

Covers:
  - RadarAnalystAgent mock response (schema, field types, signal count)
  - Radar API route: GET /api/radar/{market} (cache miss + cache hit)
  - Empty signals case (no_signals_reason populated)
  - India market radar
  - RadarSignal schema validation (conviction bounds, tickers list)
  - Cache key isolation (us ≠ india)
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.radar_analyst import RadarAnalystAgent
from main import create_app
from models.schemas import NewsItem, RadarResponse, RadarSignal


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_signals() -> list[RadarSignal]:
    return [
        RadarSignal(
            theme="AI Memory Bandwidth Squeeze",
            narrative="HBM3E supply is sold out; memory infrastructure stocks haven't re-rated.",
            tickers=["MU", "LRCX"],
            catalyst_type="macro",
            conviction=0.82,
            time_frame="2-4 weeks",
            evidence="Three analyst notes cite memory bandwidth as AI bottleneck.",
            source_headlines=["NVIDIA cites memory as bottleneck — Reuters"],
        ),
        RadarSignal(
            theme="Nuclear Power Rerating",
            narrative="Two tech hyperscalers signed nuclear PPAs this week.",
            tickers=["CEG", "VST"],
            catalyst_type="partnership",
            conviction=0.75,
            time_frame="1-2 weeks",
            evidence="2 GW of contracted nuclear capacity announced in 48 hours.",
            source_headlines=["Microsoft, Google sign nuclear deals for AI — FT"],
        ),
    ]


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_news_fetcher():
    fetcher = MagicMock()
    fetcher.get_market_news = AsyncMock(return_value=[
        NewsItem(title="NVIDIA cites memory bandwidth as key AI bottleneck", source="Reuters"),
        NewsItem(title="Microsoft, Google sign nuclear deals for AI data centres", source="FT"),
    ])
    return fetcher


@pytest.fixture
def mock_radar_analyst(mock_signals):
    analyst = MagicMock(spec=RadarAnalystAgent)
    analyst.scan = AsyncMock(return_value=(mock_signals, None))
    return analyst


@pytest.fixture
def client(mock_cache, mock_news_fetcher, mock_radar_analyst):
    """API test client with all external dependencies overridden."""
    from api import deps
    app = create_app()
    app.dependency_overrides[deps.get_cache] = lambda: mock_cache
    app.dependency_overrides[deps.get_news_fetcher] = lambda: mock_news_fetcher
    app.dependency_overrides[deps.get_radar_analyst] = lambda: mock_radar_analyst
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Agent unit tests ──────────────────────────────────────────────────────────

class TestRadarAnalystAgent:
    async def test_mock_returns_list_of_signals(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        agent = RadarAnalystAgent(settings)
        signals, reason = await agent.scan([], "us")
        assert isinstance(signals, list)
        assert len(signals) > 0

    async def test_mock_signal_schema(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        agent = RadarAnalystAgent(settings)
        signals, _ = await agent.scan([], "us")
        for s in signals:
            assert isinstance(s, RadarSignal)
            assert 0 <= s.conviction <= 1
            assert len(s.tickers) >= 1
            assert len(s.theme) > 0
            assert len(s.narrative) > 0
            assert s.catalyst_type in [
                "earnings", "fda_approval", "acquisition", "partnership",
                "analyst_upgrade", "macro", "technical", "regulatory", "unknown",
            ]

    async def test_mock_returns_none_reason_when_signals_present(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        agent = RadarAnalystAgent(settings)
        _, reason = await agent.scan([], "us")
        assert reason is None


# ── Schema validation ─────────────────────────────────────────────────────────

class TestRadarSchema:
    def test_radar_signal_conviction_bounds(self):
        signal = RadarSignal(
            theme="Test", narrative="test", tickers=["AAPL"],
            catalyst_type="macro", conviction=0.75,
            time_frame="1 week", evidence="test",
            source_headlines=["headline"],
        )
        assert signal.conviction == 0.75

    def test_radar_signal_conviction_below_zero_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            RadarSignal(
                theme="Test", narrative="test", tickers=["AAPL"],
                catalyst_type="macro", conviction=-0.1,
                time_frame="1 week", evidence="test", source_headlines=[],
            )

    def test_radar_signal_conviction_above_one_raises(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            RadarSignal(
                theme="Test", narrative="test", tickers=["AAPL"],
                catalyst_type="macro", conviction=1.1,
                time_frame="1 week", evidence="test", source_headlines=[],
            )

    def test_radar_response_defaults(self):
        resp = RadarResponse(market="us", signals=[])
        assert resp.from_cache is False
        assert isinstance(resp.generated_at, datetime)
        assert resp.no_signals_reason is None


# ── API route tests ───────────────────────────────────────────────────────────

class TestRadarAPI:
    def test_returns_200(self, client):
        resp = client.get("/api/radar/us")
        assert resp.status_code == 200

    def test_response_has_signals(self, client):
        data = client.get("/api/radar/us").json()
        assert "signals" in data
        assert isinstance(data["signals"], list)

    def test_signals_have_required_fields(self, client):
        signals = client.get("/api/radar/us").json()["signals"]
        for s in signals:
            assert "theme" in s
            assert "narrative" in s
            assert "tickers" in s
            assert "conviction" in s
            assert "time_frame" in s
            assert "evidence" in s
            assert "source_headlines" in s
            assert "catalyst_type" in s

    def test_conviction_in_valid_range(self, client):
        signals = client.get("/api/radar/us").json()["signals"]
        for s in signals:
            assert 0 <= s["conviction"] <= 1

    def test_not_cached_on_first_call(self, client):
        data = client.get("/api/radar/us").json()
        assert data["from_cache"] is False

    def test_cached_on_second_call(self, mock_cache, mock_news_fetcher, mock_radar_analyst, mock_signals):
        cached_payload = RadarResponse(
            market="us",
            signals=mock_signals,
            from_cache=True,
        ).model_dump()
        mock_cache.get = AsyncMock(return_value=cached_payload)

        from api import deps
        app = create_app()
        app.dependency_overrides[deps.get_cache] = lambda: mock_cache
        app.dependency_overrides[deps.get_news_fetcher] = lambda: mock_news_fetcher
        app.dependency_overrides[deps.get_radar_analyst] = lambda: mock_radar_analyst

        with TestClient(app) as c:
            data = c.get("/api/radar/us").json()
        app.dependency_overrides.clear()

        assert data["from_cache"] is True
        mock_radar_analyst.scan.assert_not_called()

    def test_india_market_returns_200(self, client):
        resp = client.get("/api/radar/india")
        assert resp.status_code == 200

    def test_market_isolation_different_keys(self, mock_cache, mock_news_fetcher, mock_radar_analyst):
        """US and India radar must use different cache keys."""
        keys_set: list[str] = []

        async def record_set(key, value, ttl):
            keys_set.append(key)

        mock_cache.set = record_set

        from api import deps
        app = create_app()
        app.dependency_overrides[deps.get_cache] = lambda: mock_cache
        app.dependency_overrides[deps.get_news_fetcher] = lambda: mock_news_fetcher
        app.dependency_overrides[deps.get_radar_analyst] = lambda: mock_radar_analyst

        with TestClient(app) as c:
            c.get("/api/radar/us")
            c.get("/api/radar/india")
        app.dependency_overrides.clear()

        assert len(set(keys_set)) == 2, f"Expected 2 distinct cache keys, got: {keys_set}"

    def test_empty_signals_case(self, mock_cache, mock_news_fetcher):
        """When AI returns 0 signals, endpoint returns empty list with reason."""
        mock_analyst = MagicMock(spec=RadarAnalystAgent)
        mock_analyst.scan = AsyncMock(
            return_value=([], "No structural themes with sufficient evidence today")
        )
        from api import deps
        app = create_app()
        app.dependency_overrides[deps.get_cache] = lambda: mock_cache
        app.dependency_overrides[deps.get_news_fetcher] = lambda: mock_news_fetcher
        app.dependency_overrides[deps.get_radar_analyst] = lambda: mock_analyst
        with TestClient(app) as c:
            data = c.get("/api/radar/us").json()
        app.dependency_overrides.clear()

        assert data["signals"] == []
        assert data["no_signals_reason"] is not None
        assert len(data["no_signals_reason"]) > 0

    def test_no_news_returns_empty_signals(self, mock_cache, mock_radar_analyst):
        """When news fetcher returns nothing, return empty signals gracefully."""
        fetcher = MagicMock()
        fetcher.get_market_news = AsyncMock(return_value=[])

        from api import deps
        app = create_app()
        app.dependency_overrides[deps.get_cache] = lambda: mock_cache
        app.dependency_overrides[deps.get_news_fetcher] = lambda: fetcher
        app.dependency_overrides[deps.get_radar_analyst] = lambda: mock_radar_analyst
        with TestClient(app) as c:
            data = c.get("/api/radar/us").json()
        app.dependency_overrides.clear()

        assert data["signals"] == []
        mock_radar_analyst.scan.assert_not_called()

    def test_response_has_generated_at(self, client):
        data = client.get("/api/radar/us").json()
        assert "generated_at" in data

    def test_response_has_market_field(self, client):
        data = client.get("/api/radar/us").json()
        assert data["market"] == "us"

    def test_tickers_are_strings(self, client):
        signals = client.get("/api/radar/us").json()["signals"]
        for s in signals:
            assert all(isinstance(t, str) for t in s["tickers"])
