"""Tests for services/fundamental_scoring.py — no live network calls."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from services.fundamental_scoring import (
    compute_fundamental_score,
    enrich_candidates_with_fundamentals,
    get_fundamental_score,
)


class TestComputeFundamentalScore:
    """Unit tests for the pure scoring function — no I/O."""

    def _make_info(self, **kwargs) -> dict:
        defaults = {
            "returnOnEquity":          0.18,   # 18% ROE
            "revenueGrowth":           0.15,   # 15% revenue growth
            "debtToEquity":            30.0,   # 0.30x D/E
            "heldPercentInstitutions": 0.25,   # 25% institutional
            "trailingPE":              22.0,
            "profitMargins":           0.12,
        }
        defaults.update(kwargs)
        return defaults

    def test_strong_fundamentals_score_high_aggressive(self) -> None:
        info = self._make_info(
            returnOnEquity=0.25,
            revenueGrowth=0.30,
            debtToEquity=10.0,
            heldPercentInstitutions=0.40,
        )
        result = compute_fundamental_score(info, five_yr_cagr=0.22, market="india", risk_profile="aggressive")
        assert result["fundamental_score"] >= 8.0
        assert result["grade"] == "A"
        assert result["warnings"] == []

    def test_negative_5yr_return_scores_low_and_warns(self) -> None:
        info = self._make_info()
        result = compute_fundamental_score(info, five_yr_cagr=-0.03, market="india", risk_profile="aggressive")
        assert result["fundamental_score"] < 6.0
        assert any("Negative 5-year return" in w for w in result["warnings"])

    def test_negative_roe_warns(self) -> None:
        info = self._make_info(returnOnEquity=-0.05)
        result = compute_fundamental_score(info, five_yr_cagr=0.10, market="india", risk_profile="moderate")
        assert any("Negative ROE" in w for w in result["warnings"])
        assert result["grade"] in ("D", "F", "C")

    def test_high_debt_warns_for_conservative(self) -> None:
        info = self._make_info(debtToEquity=200.0)   # 2.0x D/E
        result = compute_fundamental_score(info, five_yr_cagr=0.14, market="india", risk_profile="conservative")
        assert any("leverage" in w.lower() for w in result["warnings"])

    def test_high_pe_penalises_conservative_not_aggressive(self) -> None:
        info = self._make_info(trailingPE=45.0)
        conservative = compute_fundamental_score(info, five_yr_cagr=0.15, market="india", risk_profile="conservative")
        aggressive   = compute_fundamental_score(info, five_yr_cagr=0.15, market="india", risk_profile="aggressive")
        assert conservative["fundamental_score"] < aggressive["fundamental_score"]

    def test_missing_data_returns_neutral_score(self) -> None:
        result = compute_fundamental_score({}, five_yr_cagr=None, market="india", risk_profile="moderate")
        # All components are neutral (5.0) → weighted sum ≈ 5.0
        assert 3.0 <= result["fundamental_score"] <= 7.0

    def test_grade_thresholds(self) -> None:
        high  = compute_fundamental_score(self._make_info(returnOnEquity=0.25, revenueGrowth=0.25, debtToEquity=5.0), 0.20, "india", "aggressive")
        low   = compute_fundamental_score(self._make_info(returnOnEquity=-0.10, revenueGrowth=-0.15, debtToEquity=300.0), -0.05, "india", "aggressive")
        assert high["grade"] in ("A", "B")
        assert low["grade"] in ("D", "F")

    def test_key_metrics_populated(self) -> None:
        info = self._make_info()
        result = compute_fundamental_score(info, five_yr_cagr=0.15, market="india", risk_profile="moderate")
        assert "roe" in result["key_metrics"]
        assert "revenue_growth" in result["key_metrics"]
        assert "pe_ratio" in result["key_metrics"]
        assert "5yr_cagr" in result["key_metrics"]

    def test_dividend_bonus_for_conservative(self) -> None:
        info_div    = self._make_info(dividendYield=0.03)   # 3% dividend
        info_no_div = self._make_info(dividendYield=0.0)
        with_div    = compute_fundamental_score(info_div,    0.12, "india", "conservative")
        without_div = compute_fundamental_score(info_no_div, 0.12, "india", "conservative")
        assert with_div["fundamental_score"] >= without_div["fundamental_score"]

    def test_earnings_growth_bonus_for_aggressive(self) -> None:
        info_fast = self._make_info(earningsGrowth=0.25)
        info_slow = self._make_info(earningsGrowth=0.05)
        fast = compute_fundamental_score(info_fast, 0.15, "india", "aggressive")
        slow = compute_fundamental_score(info_slow, 0.15, "india", "aggressive")
        assert fast["fundamental_score"] >= slow["fundamental_score"]


class TestEnrichCandidates:
    """Integration-level tests for the enrichment pipeline — mocked I/O."""

    @pytest.fixture
    def mock_cache(self):
        cache = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
        return cache

    @pytest.fixture
    def good_result(self) -> dict:
        return {
            "fundamental_score": 7.5,
            "grade": "B",
            "breakdown": {},
            "warnings": [],
            "key_metrics": {"roe": "18.0%", "5yr_cagr": "15.0%"},
        }

    @pytest.mark.asyncio
    async def test_enrich_patches_candidates(self, mock_cache, good_result) -> None:
        candidates = [{"ticker": "HDFC", "name": "HDFC Bank", "sector": "Finance"}]
        with patch(
            "services.fundamental_scoring.get_fundamental_score",
            new=AsyncMock(return_value=good_result),
        ):
            result = await enrich_candidates_with_fundamentals(
                candidates, "india", "aggressive", mock_cache
            )
        assert result[0]["fundamental_score"] == 7.5
        assert result[0]["grade"] == "B"

    @pytest.mark.asyncio
    async def test_enrich_survives_individual_failure(self, mock_cache) -> None:
        """A fetch failure for one ticker must not prevent others from being enriched."""
        candidates = [
            {"ticker": "GOOD", "name": "Good Co"},
            {"ticker": "BAD",  "name": "Bad Co"},
        ]
        good_result = {"fundamental_score": 8.0, "grade": "A", "breakdown": {}, "warnings": [], "key_metrics": {}}

        async def _mock_get(ticker, market, risk_profile, cache):
            if ticker == "BAD":
                raise RuntimeError("yfinance timeout")
            return good_result

        with patch("services.fundamental_scoring.get_fundamental_score", new=_mock_get):
            result = await enrich_candidates_with_fundamentals(
                candidates, "india", "moderate", mock_cache
            )

        assert result[0].get("fundamental_score") == 8.0
        assert "fundamental_score" not in result[1]   # BAD was skipped cleanly

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self, mock_cache) -> None:
        result = await enrich_candidates_with_fundamentals([], "us", "conservative", mock_cache)
        assert result == []
