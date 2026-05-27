from __future__ import annotations

import pytest

from agents.gainer_analyst import GainerAnalystAgent
from agents.predictor import PredictorAgent
from core.config import get_settings
from models.schemas import FundamentalsData, GainerAnalysis, NewsItem


@pytest.fixture
def analyst() -> GainerAnalystAgent:
    get_settings.cache_clear()
    return GainerAnalystAgent(get_settings())


@pytest.fixture
def predictor() -> PredictorAgent:
    get_settings.cache_clear()
    return PredictorAgent(get_settings())


class TestGainerAnalystAgent:
    async def test_mock_returns_valid_analysis(self, analyst: GainerAnalystAgent) -> None:
        result = await analyst.analyse(
            ticker="NVDA",
            change_pct=8.5,
            company_name="NVIDIA Corporation",
            sector="Technology",
            news=[NewsItem(title="NVIDIA beats earnings", source="Reuters")],
        )
        assert isinstance(result, GainerAnalysis)
        assert result.ticker == "NVDA"
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.key_catalysts) > 0
        assert result.why_it_gained != ""

    async def test_mock_returns_valid_catalyst_type(self, analyst: GainerAnalystAgent) -> None:
        result = await analyst.analyse(
            ticker="TEST",
            change_pct=5.0,
            company_name="Test Corp",
            sector=None,
            news=[],
        )
        valid_types = {
            "earnings", "fda_approval", "acquisition", "partnership",
            "analyst_upgrade", "macro", "technical", "regulatory", "unknown",
        }
        assert result.catalyst_type in valid_types

    async def test_mock_returns_valid_sentiment(self, analyst: GainerAnalystAgent) -> None:
        result = await analyst.analyse(
            ticker="TEST",
            change_pct=5.0,
            company_name="Test Corp",
            sector=None,
            news=[],
        )
        valid_sentiments = {"very_positive", "positive", "neutral", "negative", "very_negative"}
        assert result.sentiment in valid_sentiments


class TestPredictorAgent:
    async def test_mock_returns_valid_prediction(
        self, predictor: PredictorAgent, sample_gainer_analysis: GainerAnalysis
    ) -> None:
        result = await predictor.predict(
            ticker="NVDA",
            company_name="NVIDIA Corporation",
            fundamentals=FundamentalsData(pe_ratio=45.0, roe=0.32),
            analysis=sample_gainer_analysis,
        )
        assert result.ticker == "NVDA"
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.key_risks) > 0
        assert len(result.key_tailwinds) > 0
        assert result.disclaimer != ""

    async def test_prediction_includes_disclaimer(
        self, predictor: PredictorAgent, sample_gainer_analysis: GainerAnalysis
    ) -> None:
        result = await predictor.predict(
            ticker="NVDA",
            company_name="NVIDIA",
            fundamentals=FundamentalsData(),
            analysis=sample_gainer_analysis,
        )
        assert "educational purposes" in result.disclaimer.lower()
        assert "not investment advice" in result.disclaimer.lower()

    async def test_prediction_valid_horizon(
        self, predictor: PredictorAgent, sample_gainer_analysis: GainerAnalysis
    ) -> None:
        result = await predictor.predict(
            ticker="TEST",
            company_name="Test",
            fundamentals=FundamentalsData(),
            analysis=sample_gainer_analysis,
        )
        assert result.time_horizon in {"days", "weeks", "months"}
