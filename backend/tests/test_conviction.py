"""
Tests for the conviction thesis feature.

Covers:
  - ThesisAnalystAgent mock response (schema, field types, instrument count)
  - Conviction API route: POST /api/conviction/analyse (cache miss + cache hit)
  - Cache key stability (same belief → same key, different beliefs → different keys)
  - Conviction schema validation
"""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import create_app
from models.schemas import (
    ConvictionRequest,
    ConvictionResponse,
    ThesisConviction,
    ThesisConfirmer,
    ThesisInstrument,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conviction() -> ThesisConviction:
    return ThesisConviction(
        belief="AI will drive memory demand",
        theme_label="AI MEMORY DEMAND",
        conviction_score=81.0,
        thesis_summary="HBM demand from AI data centers is a multi-year structural shift.",
        instruments=[
            ThesisInstrument(ticker="SMH", name="VanEck Semiconductor ETF", risk_level="lower",
                             description="Diversified basket", rationale="Spreads exposure."),
            ThesisInstrument(ticker="MU", name="Micron Technology", risk_level="focused",
                             description="Pure-play US DRAM", rationale="Only US DRAM maker."),
            ThesisInstrument(ticker="NVDA", name="NVIDIA", risk_level="higher",
                             description="AI infrastructure leverage", rationale="GPU = memory demand."),
        ],
        confirmers=[
            ThesisConfirmer(text="NVDA H100 backlog extending to late 2025", status="confirmed"),
            ThesisConfirmer(text="Samsung adding DRAM capacity", status="watch"),
            ThesisConfirmer(text="Export restrictions on NVDA", status="risk"),
        ],
        entry_signal="fair",
        entry_explanation="Stocks have re-rated — fair entry, not ideal.",
        exit_triggers=["DRAM spot -15% for 3 months", "NVDA cuts data center guidance 20%"],
        time_horizon="multi-year",
    )


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_analyst(mock_conviction):
    analyst = MagicMock()
    analyst.analyse = AsyncMock(return_value=mock_conviction)
    return analyst


@pytest.fixture
def client(mock_cache, mock_analyst):
    from core.user_auth import create_access_token

    app = create_app()
    from api import deps
    app.dependency_overrides[deps.get_cache] = lambda: mock_cache
    app.dependency_overrides[deps.get_thesis_analyst] = lambda: mock_analyst
    # Must match TEST_JWT_SECRET set by mock_settings fixture in conftest
    token = create_access_token("test-user-123", "testuser", "test-secret-key-stockcoach", expire_days=1)
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c
    app.dependency_overrides.clear()


# ── Schema tests ──────────────────────────────────────────────────────────────

class TestConvictionSchema:
    def test_conviction_score_range(self, mock_conviction):
        assert 0 <= mock_conviction.conviction_score <= 100

    def test_theme_label_is_uppercase(self, mock_conviction):
        assert mock_conviction.theme_label == mock_conviction.theme_label.upper()

    def test_instruments_has_all_three_risk_levels(self, mock_conviction):
        levels = {i.risk_level for i in mock_conviction.instruments}
        assert levels == {"lower", "focused", "higher"}

    def test_confirmers_have_valid_statuses(self, mock_conviction):
        valid = {"confirmed", "watch", "risk"}
        for c in mock_conviction.confirmers:
            assert c.status in valid

    def test_entry_signal_is_valid(self, mock_conviction):
        assert mock_conviction.entry_signal in ("strong", "fair", "wait")

    def test_exit_triggers_not_empty(self, mock_conviction):
        assert len(mock_conviction.exit_triggers) >= 1

    def test_conviction_score_invalid_raises(self):
        with pytest.raises(Exception):
            ThesisConviction(
                belief="test",
                theme_label="TEST",
                conviction_score=150,  # > 100 — invalid
                thesis_summary="summary",
                instruments=[],
                confirmers=[],
                entry_signal="fair",
                entry_explanation="ok",
                exit_triggers=[],
                time_horizon="1 year",
            )


# ── API tests ─────────────────────────────────────────────────────────────────

class TestConvictionAPI:
    def test_analyse_returns_200(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "AI drives memory demand", "market": "us"})
        assert resp.status_code == 200

    def test_analyse_response_has_conviction(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "AI drives memory demand", "market": "us"})
        data = resp.json()
        assert "conviction" in data
        assert "theme_label" in data["conviction"]
        assert "conviction_score" in data["conviction"]

    def test_analyse_response_has_instruments(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "AI drives memory demand", "market": "us"})
        instruments = resp.json()["conviction"]["instruments"]
        assert len(instruments) == 3
        risk_levels = {i["risk_level"] for i in instruments}
        assert risk_levels == {"lower", "focused", "higher"}

    def test_analyse_not_cached_on_first_call(self, client, mock_cache):
        client.post("/api/conviction/analyse", json={"belief": "Nuclear energy comeback", "market": "us"})
        mock_cache.set.assert_called_once()

    def test_analyse_served_from_cache_on_second_call(self, client, mock_cache, mock_conviction):
        # Set up cache to return data on second call
        mock_cache.get = AsyncMock(return_value={
            "conviction": mock_conviction.model_dump(),
            "analysed_at": "2026-01-01T00:00:00",
        })
        resp = client.post("/api/conviction/analyse", json={"belief": "AI drives memory demand", "market": "us"})
        assert resp.status_code == 200
        assert resp.json()["from_cache"] is True
        mock_cache.set.assert_not_called()

    def test_empty_belief_rejected(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "    ", "market": "us"})
        # FastAPI Pydantic validation rejects min_length=5 violation
        assert resp.status_code == 422

    def test_too_long_belief_rejected(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "x" * 501, "market": "us"})
        assert resp.status_code == 422

    def test_invalid_market_rejected(self, client):
        resp = client.post("/api/conviction/analyse", json={"belief": "AI drives memory", "market": "china"})
        assert resp.status_code == 422


# ── Cache key tests ───────────────────────────────────────────────────────────

class TestCacheKey:
    def _key(self, belief: str, market: str = "us") -> str:
        from api.routes.conviction import _conviction_cache_key
        return _conviction_cache_key(belief, market)

    def test_same_belief_same_key(self):
        assert self._key("AI memory") == self._key("AI memory")

    def test_case_insensitive(self):
        assert self._key("AI Memory") == self._key("ai memory")

    def test_different_beliefs_different_keys(self):
        assert self._key("AI memory") != self._key("Nuclear energy")

    def test_different_markets_different_keys(self):
        assert self._key("AI memory", "us") != self._key("AI memory", "india")

    def test_key_is_stable_format(self):
        key = self._key("test belief", "us")
        assert key.startswith("conviction:us:")
        # Hash portion is 16 hex chars
        parts = key.split(":")
        assert len(parts[2]) == 16


# ── Mock agent tests ──────────────────────────────────────────────────────────

class TestThesisAnalystMock:
    @pytest.mark.asyncio
    async def test_mock_returns_valid_conviction(self):
        from core.config import Settings
        from agents.thesis_analyst import ThesisAnalystAgent
        settings = Settings(mock_ai=True)
        agent = ThesisAnalystAgent(settings)
        result = await agent.analyse("I believe AI drives memory demand")
        assert isinstance(result, ThesisConviction)
        assert 0 <= result.conviction_score <= 100
        assert len(result.instruments) == 3
        assert result.entry_signal in ("strong", "fair", "wait")

    @pytest.mark.asyncio
    async def test_mock_instruments_cover_all_risk_levels(self):
        from core.config import Settings
        from agents.thesis_analyst import ThesisAnalystAgent
        settings = Settings(mock_ai=True)
        agent = ThesisAnalystAgent(settings)
        result = await agent.analyse("test belief")
        risk_levels = {i.risk_level for i in result.instruments}
        assert risk_levels == {"lower", "focused", "higher"}

    @pytest.mark.asyncio
    async def test_mock_theme_label_is_uppercase(self):
        from core.config import Settings
        from agents.thesis_analyst import ThesisAnalystAgent
        settings = Settings(mock_ai=True)
        agent = ThesisAnalystAgent(settings)
        result = await agent.analyse("test")
        assert result.theme_label == result.theme_label.upper()
