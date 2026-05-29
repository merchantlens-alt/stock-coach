from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import (
    FundamentalsData,
    GainerAnalysis,
    MarketSummary,
    NewsItem,
    StockGainer,
    StockPrediction,
)


# ── Settings override ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never touch GCP or real APIs."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("MOCK_AI", "true")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("NEWS_API_KEY", "")


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    """
    Reset all module-level dep singletons and the settings cache before each
    test so tests start from a clean state (no stale cache entries, no stale
    agent instances carrying incorrect config).
    """
    import api.deps as deps
    from core.config import get_settings

    deps._cache = None
    deps._market_data = None
    deps._news_fetcher = None
    deps._gainer_analyst = None
    deps._market_analyst = None
    deps._thesis_analyst = None
    deps._radar_analyst = None
    get_settings.cache_clear()


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_us_gainer() -> StockGainer:
    return StockGainer(
        ticker="NVDA",
        name="NVIDIA Corporation",
        market="us",
        price=950.0,
        change_pct=8.5,
        change_abs=74.5,
        volume=45_000_000,
        avg_volume=40_000_000,
        market_cap=2_300_000_000_000,
        sector="Technology",
        industry="Semiconductors",
    )


@pytest.fixture
def sample_india_gainer() -> StockGainer:
    return StockGainer(
        ticker="RELIANCE",
        name="Reliance Industries Ltd",
        market="india",
        price=2850.0,
        change_pct=5.2,
        change_abs=141.0,
        volume=8_000_000,
        market_cap=19_000_000_000_000,
        sector="Energy",
    )


@pytest.fixture
def sample_fundamentals() -> FundamentalsData:
    return FundamentalsData(
        pe_ratio=45.2,
        forward_pe=30.1,
        roe=0.32,
        debt_equity=0.45,
        revenue_growth_yoy=0.18,
        earnings_growth_yoy=0.42,
        profit_margin=0.55,
        fifty_two_week_high=1000.0,
        fifty_two_week_low=400.0,
        analyst_target_price=1100.0,
        analyst_recommendation="buy",
    )


@pytest.fixture
def sample_news() -> list[NewsItem]:
    return [
        NewsItem(title="NVIDIA beats earnings estimates by 20%", source="Reuters"),
        NewsItem(title="Data center revenue surges on AI demand", source="Bloomberg"),
        NewsItem(title="Analyst raises NVDA price target to $1200", source="CNBC"),
    ]


@pytest.fixture
def sample_gainer_analysis(sample_us_gainer: StockGainer) -> GainerAnalysis:
    return GainerAnalysis(
        ticker=sample_us_gainer.ticker,
        why_it_gained="NVIDIA surged following a blowout earnings beat driven by AI chip demand.",
        key_catalysts=["Earnings beat by 20%", "Data center revenue +427% YoY"],
        catalyst_type="earnings",
        sentiment="very_positive",
        is_sustained=True,
        sustainability_reason="AI chip demand is structural, not a one-time event.",
        confidence=0.85,
        related_beneficiaries=["AMD", "AVGO", "SMCI"],
        beneficiary_reasoning=(
            "AMD and AVGO are in the same semiconductor supply chain. "
            "SMCI benefits directly from AI server demand driven by NVDA chips."
        ),
    )


@pytest.fixture
def sample_market_summary() -> MarketSummary:
    return MarketSummary(
        market="us",
        narrative=(
            "Today's gainers are concentrated in AI infrastructure and semiconductor names, "
            "suggesting institutional rotation into high-growth tech ahead of upcoming earnings."
        ),
        themes=["AI infrastructure demand", "Semiconductor supply chain recovery"],
        dominant_sector="Technology",
        sentiment="bullish",
        watch_list=["NVDA", "AMD", "SMCI"],
        watch_reason=(
            "Semiconductor names not yet in today's list may follow in 1-3 days "
            "as institutional rotation broadens."
        ),
    )


@pytest.fixture
def sample_prediction(sample_us_gainer: StockGainer) -> StockPrediction:
    return StockPrediction(
        ticker=sample_us_gainer.ticker,
        outlook="NVIDIA's AI tailwind remains strong; further upside likely over weeks.",
        predicted_change_pct=6.0,
        confidence=0.65,
        time_horizon="weeks",
        key_risks=["Valuation stretched", "Market correction risk"],
        key_tailwinds=["AI spending acceleration", "Earnings momentum"],
        valuation_signal="overvalued",
        growth_signal="strong",
        debt_signal="strong",
    )


# ── App client ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    # Import after env vars are patched
    from main import create_app

    return TestClient(create_app())
