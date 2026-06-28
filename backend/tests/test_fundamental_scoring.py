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
        info_div    = self._make_info(dividendYield=3.0)   # 3% (yfinance percent form)
        info_no_div = self._make_info(dividendYield=0.0)
        with_div    = compute_fundamental_score(info_div,    0.12, "india", "conservative")
        without_div = compute_fundamental_score(info_no_div, 0.12, "india", "conservative")
        assert with_div["fundamental_score"] >= without_div["fundamental_score"]

    def test_dividend_yield_displayed_as_percent_not_multiplied(self) -> None:
        """yfinance returns dividendYield already as a percent — must NOT ×100 (552% bug)."""
        info = self._make_info(dividendYield=5.52)   # ITC-style 5.52%
        result = compute_fundamental_score(info, 0.12, "india", "moderate")
        assert result["key_metrics"]["dividend_yield"] == "5.5%"

    def test_earnings_growth_bonus_for_aggressive(self) -> None:
        info_fast = self._make_info(earningsGrowth=0.25)
        info_slow = self._make_info(earningsGrowth=0.05)
        fast = compute_fundamental_score(info_fast, 0.15, "india", "aggressive")
        slow = compute_fundamental_score(info_slow, 0.15, "india", "aggressive")
        assert fast["fundamental_score"] >= slow["fundamental_score"]

    # ── Valuation component ──────────────────────────────────────────────────

    def test_valuation_in_breakdown_and_metrics(self) -> None:
        info = self._make_info(priceToBook=3.0)
        result = compute_fundamental_score(info, 0.15, "india", "moderate")
        assert "valuation" in result["breakdown"]
        assert "price_to_book" in result["key_metrics"]

    def test_high_pb_unsupported_by_roe_is_penalised_and_warns(self) -> None:
        """High P/B with MEDIOCRE ROE = genuinely overvalued → penalise + warn."""
        weak_roe = dict(returnOnEquity=0.10, revenueGrowth=0.10, debtToEquity=40.0,
                        heldPercentInstitutions=0.20, trailingPE=20.0)
        fair      = compute_fundamental_score({**weak_roe, "priceToBook": 2.0},  0.12, "india", "moderate")
        expensive = compute_fundamental_score({**weak_roe, "priceToBook": 9.0},  0.12, "india", "moderate")
        assert expensive["fundamental_score"] < fair["fundamental_score"]
        assert any("P/B" in w for w in expensive["warnings"])

    def test_high_pb_justified_by_high_roe_is_not_penalised(self) -> None:
        """SUZLON-style: 8x book but 40% ROE and reasonable P/E → no P/B penalty or warning."""
        suzlon = dict(returnOnEquity=0.40, revenueGrowth=0.45, debtToEquity=6.0,
                      heldPercentInstitutions=0.21, trailingPE=24.7, priceToBook=8.3)
        result = compute_fundamental_score(suzlon, 0.52, "india", "moderate")
        assert not any("P/B" in w for w in result["warnings"])
        # P/E 24.7 is "fair" — valuation should not be in the very-expensive band
        assert "fair" in result["breakdown"]["valuation"].lower()

    # ── Cyclical valuation (P/B anchor, not P/E) ─────────────────────────────

    def test_cyclical_trough_high_pe_low_pb_is_not_penalised(self) -> None:
        """A steel stock in a downturn: high P/E on depressed earnings, but P/B ~1x = cheap."""
        base = dict(returnOnEquity=0.08, revenueGrowth=0.05, debtToEquity=60.0,
                    heldPercentInstitutions=0.30, sector="Basic Materials")
        cyclical_cheap = compute_fundamental_score({**base, "trailingPE": 55.0, "priceToBook": 1.0},
                                                   0.10, "india", "moderate")
        # Same P/E in a NON-cyclical would read "very expensive"; here P/B 1.0 rules.
        assert "cyclical" in cyclical_cheap["breakdown"]["valuation"].lower()
        assert "cheap" in cyclical_cheap["breakdown"]["valuation"].lower()
        # No P/E warning for a cyclical
        assert not any("P/E" in w for w in cyclical_cheap["warnings"])

    def test_cyclical_peak_high_pb_warns(self) -> None:
        """A cyclical at a rich book multiple is flagged as a likely cycle peak."""
        info = dict(returnOnEquity=0.35, revenueGrowth=0.40, debtToEquity=40.0,
                    heldPercentInstitutions=0.30, trailingPE=12.0, priceToBook=5.5,
                    sector="Energy")
        result = compute_fundamental_score(info, 0.30, "india", "moderate")
        assert any("cyclical" in w.lower() for w in result["warnings"])

    def test_negative_price_to_book_does_not_score_perfect(self) -> None:
        """Buyback names (MCD, ABBV) have negative book equity — must NOT read as 'cheap'."""
        info = self._make_info(priceToBook=-149.0, trailingPE=25.0)
        result = compute_fundamental_score(info, 0.14, "us", "moderate")
        # Should fall back to P/E (25x → moderate), never the P/B<=1 perfect score
        assert "P/B" not in result["breakdown"]["valuation"]
        assert "P/E" in result["breakdown"]["valuation"]
        assert not any("P/B" in w for w in result["warnings"])

    def test_negative_pe_and_no_book_is_neutral_not_cheap(self) -> None:
        """Loss-making with no usable book value → valuation neutral, not a perfect 'cheap'."""
        info = self._make_info(priceToBook=-3.0, trailingPE=-12.0)
        result = compute_fundamental_score(info, 0.10, "us", "moderate")
        assert "unavailable" in result["breakdown"]["valuation"].lower()


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
