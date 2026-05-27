from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.gainer_analyst import GainerAnalystAgent
from agents.market_analyst import MarketAnalystAgent
from agents.predictor import PredictorAgent
from core.config import get_settings
from models.schemas import FundamentalsData, GainerAnalysis, MarketSummary, NewsItem, StockGainer


@pytest.fixture
def analyst() -> GainerAnalystAgent:
    get_settings.cache_clear()
    return GainerAnalystAgent(get_settings())


@pytest.fixture
def predictor() -> PredictorAgent:
    get_settings.cache_clear()
    return PredictorAgent(get_settings())


@pytest.fixture
def market_analyst() -> MarketAnalystAgent:
    get_settings.cache_clear()
    return MarketAnalystAgent(get_settings())


# ── GainerAnalystAgent ────────────────────────────────────────────────────────

class TestGainerAnalystAgent:
    # ── analyse() backward-compat wrapper ────────────────────────────────────

    async def test_analyse_returns_gainer_analysis(self, analyst: GainerAnalystAgent) -> None:
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

    # ── analyse_full() — combined call ────────────────────────────────────────

    async def test_analyse_full_returns_tuple(self, analyst: GainerAnalystAgent, sample_fundamentals) -> None:
        analysis, prediction = await analyst.analyse_full(
            ticker="NVDA",
            change_pct=8.5,
            company_name="NVIDIA Corporation",
            sector="Technology",
            news=[],
            fundamentals=sample_fundamentals,
        )
        assert isinstance(analysis, GainerAnalysis)
        assert analysis.ticker == "NVDA"
        assert prediction is not None
        assert prediction.ticker == "NVDA"

    async def test_analyse_full_no_fundamentals_returns_none_prediction(
        self, analyst: GainerAnalystAgent
    ) -> None:
        analysis, prediction = await analyst.analyse_full(
            ticker="NVDA",
            change_pct=8.5,
            company_name="NVIDIA Corporation",
            sector="Technology",
            news=[],
            fundamentals=None,
        )
        assert isinstance(analysis, GainerAnalysis)
        assert prediction is None  # Prediction requires fundamentals

    async def test_analyse_full_with_gainers_context_populates_comparison(
        self, analyst: GainerAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="AAPL",
            change_pct=2.1,
            company_name="Apple Inc.",
            sector="Technology",
            news=[],
            gainers_context=[sample_us_gainer],
        )
        # Mock mode builds a comparison string when context is given
        assert analysis.comparison_to_gainers is not None
        assert len(analysis.comparison_to_gainers) > 10

    async def test_analyse_full_without_gainers_context_no_comparison(
        self, analyst: GainerAnalystAgent
    ) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="NVDA",
            change_pct=8.5,
            company_name="NVIDIA Corporation",
            sector="Technology",
            news=[],
            gainers_context=None,
        )
        assert analysis.comparison_to_gainers is None

    async def test_mock_returns_valid_catalyst_type(self, analyst: GainerAnalystAgent) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="TEST", change_pct=5.0, company_name="Test Corp", sector=None, news=[]
        )
        valid_types = {
            "earnings", "fda_approval", "acquisition", "partnership",
            "analyst_upgrade", "macro", "technical", "regulatory", "unknown",
        }
        assert analysis.catalyst_type in valid_types

    async def test_mock_returns_valid_sentiment(self, analyst: GainerAnalystAgent) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="TEST", change_pct=5.0, company_name="Test Corp", sector=None, news=[]
        )
        assert analysis.sentiment in {"very_positive", "positive", "neutral", "negative", "very_negative"}

    async def test_mock_includes_related_beneficiaries(self, analyst: GainerAnalystAgent) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="NVDA", change_pct=8.5, company_name="NVIDIA", sector="Technology", news=[]
        )
        assert isinstance(analysis.related_beneficiaries, list)
        assert len(analysis.related_beneficiaries) > 0

    async def test_mock_includes_beneficiary_reasoning(self, analyst: GainerAnalystAgent) -> None:
        analysis, _ = await analyst.analyse_full(
            ticker="NVDA", change_pct=8.5, company_name="NVIDIA", sector="Technology", news=[]
        )
        assert analysis.beneficiary_reasoning is not None
        assert len(analysis.beneficiary_reasoning) > 10

    async def test_live_gemini_path_with_mocked_http(self, analyst: GainerAnalystAgent, sample_fundamentals) -> None:
        """Verify the live Gemini REST path processes a combined response correctly."""
        import httpx
        import respx
        from core.auth import clear_token_cache

        clear_token_cache()

        fake_ai_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "why_it_gained": "Strong earnings beat.",
                            "key_catalysts": ["Beat by 15%", "Raised guidance"],
                            "catalyst_type": "earnings",
                            "sentiment": "very_positive",
                            "is_sustained": True,
                            "sustainability_reason": "Structural AI demand.",
                            "analysis_confidence": 0.85,
                            "related_beneficiaries": ["AMD", "AVGO"],
                            "beneficiary_reasoning": "Same supply chain.",
                            "comparison_to_gainers": "",
                            "outlook": "Continued momentum expected.",
                            "predicted_change_pct": 5.0,
                            "prediction_confidence": 0.65,
                            "time_horizon": "weeks",
                            "key_risks": ["Valuation stretched"],
                            "key_tailwinds": ["AI demand"],
                            "valuation_signal": "overvalued",
                            "growth_signal": "strong",
                            "debt_signal": "strong",
                        })
                    }]
                }
            }]
        }

        analyst._mock = False
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=fake_ai_response)
            )
            analysis, prediction = await analyst.analyse_full(
                ticker="NVDA",
                change_pct=8.5,
                company_name="NVIDIA Corporation",
                sector="Technology",
                news=[NewsItem(title="NVDA beats earnings", source="Reuters")],
                fundamentals=sample_fundamentals,
            )

        assert analysis.ticker == "NVDA"
        assert analysis.catalyst_type == "earnings"
        assert "AMD" in analysis.related_beneficiaries
        assert prediction is not None
        assert prediction.time_horizon == "weeks"


# ── PredictorAgent ────────────────────────────────────────────────────────────

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

    async def test_prediction_with_empty_fundamentals(
        self, predictor: PredictorAgent, sample_gainer_analysis: GainerAnalysis
    ) -> None:
        """Predictor should still work when all fundamental fields are None."""
        result = await predictor.predict(
            ticker="NVDA",
            company_name="NVIDIA",
            fundamentals=FundamentalsData(),  # All None
            analysis=sample_gainer_analysis,
        )
        assert result.ticker == "NVDA"

    async def test_live_gemini_path_with_mocked_http(
        self, predictor: PredictorAgent, sample_gainer_analysis: GainerAnalysis
    ) -> None:
        """Verify the live Gemini REST path processes a valid response correctly."""
        import httpx
        import respx
        from core.auth import clear_token_cache

        clear_token_cache()

        fake_ai_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "outlook": "Strong AI tailwind supports continued momentum over weeks.",
                            "predicted_change_pct": 6.5,
                            "confidence": 0.65,
                            "time_horizon": "weeks",
                            "key_risks": ["Valuation stretched", "Broader market correction"],
                            "key_tailwinds": ["AI demand acceleration", "Earnings momentum"],
                            "valuation_signal": "overvalued",
                            "growth_signal": "strong",
                            "debt_signal": "strong",
                        })
                    }]
                }
            }]
        }

        predictor._mock = False
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=fake_ai_response)
            )
            result = await predictor.predict(
                ticker="NVDA",
                company_name="NVIDIA",
                fundamentals=FundamentalsData(pe_ratio=45.0),
                analysis=sample_gainer_analysis,
            )

        assert result.ticker == "NVDA"
        assert result.time_horizon == "weeks"
        assert result.confidence == 0.65
        assert "not investment advice" in result.disclaimer.lower()


# ── MarketAnalystAgent ────────────────────────────────────────────────────────

class TestMarketAnalystAgent:
    async def test_mock_returns_valid_market_summary(
        self, market_analyst: MarketAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        result = await market_analyst.analyse([sample_us_gainer], "us")
        assert isinstance(result, MarketSummary)
        assert result.market == "us"
        assert result.narrative != ""
        assert len(result.themes) > 0
        assert len(result.watch_list) > 0
        assert result.watch_reason != ""

    async def test_mock_valid_sentiment_value(
        self, market_analyst: MarketAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        result = await market_analyst.analyse([sample_us_gainer], "us")
        valid = {"very_bullish", "bullish", "mixed", "bearish", "very_bearish"}
        assert result.sentiment in valid

    async def test_mock_india_market_tag_preserved(
        self, market_analyst: MarketAnalystAgent, sample_india_gainer: StockGainer
    ) -> None:
        result = await market_analyst.analyse([sample_india_gainer], "india")
        assert result.market == "india"

    async def test_mock_with_empty_gainers_list(
        self, market_analyst: MarketAnalystAgent
    ) -> None:
        """Should not crash when given an empty gainers list."""
        result = await market_analyst.analyse([], "us")
        assert isinstance(result, MarketSummary)

    async def test_mock_watch_reason_non_empty(
        self, market_analyst: MarketAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        result = await market_analyst.analyse([sample_us_gainer], "us")
        assert len(result.watch_reason) > 10

    async def test_live_gemini_path_with_mocked_http(
        self, market_analyst: MarketAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        """Verify the live Gemini REST path processes a valid response correctly."""
        import httpx
        import respx

        fake_ai_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "narrative": "AI sector powering a broad tech rally today.",
                            "themes": ["AI infrastructure", "Cloud computing"],
                            "dominant_sector": "Technology",
                            "sentiment": "bullish",
                            "watch_list": ["AMD", "SMCI"],
                            "watch_reason": "Follow-through expected in coming sessions.",
                        })
                    }]
                }
            }]
        }

        market_analyst._mock = False
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=fake_ai_response)
            )
            result = await market_analyst.analyse([sample_us_gainer], "us")

        assert result.sentiment == "bullish"
        assert result.dominant_sector == "Technology"
        assert "AMD" in result.watch_list
        assert "AI" in result.narrative

    async def test_live_gemini_invalid_json_raises(
        self, market_analyst: MarketAnalystAgent, sample_us_gainer: StockGainer
    ) -> None:
        """Garbage response from Gemini should raise AIAgentError."""
        import httpx
        import respx
        from core.exceptions import AIAgentError

        fake_bad_response = {
            "candidates": [{
                "content": {"parts": [{"text": "not valid json {{{{"}]}
            }]
        }

        market_analyst._mock = False
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=fake_bad_response)
            )
            with pytest.raises(AIAgentError):
                await market_analyst.analyse([sample_us_gainer], "us")
