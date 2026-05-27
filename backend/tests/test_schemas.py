from __future__ import annotations

import pytest

from models.schemas import (
    GainerAnalysis,
    MarketSummary,
    StockGainer,
    compute_quality_score,
)


class TestComputeQualityScore:
    """Pure-function tests for the rule-based quality scoring algorithm."""

    # ── Price tier ────────────────────────────────────────────────────────────

    def test_price_above_50_max_price_contribution(self) -> None:
        # price>=50 (2.5) + vol>=20M (3.0) + change 10% sweet spot (2.5) + ticker 4 chars (1.0)
        # raw=9.0 → normalized = min(10, round(9.0*10/9, 1)) = 10.0
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=10.0, ticker="AAPL")
        assert score == 10.0

    def test_price_20_to_49(self) -> None:
        # price 20-49 → 2.0; total raw = 2.0+3.0+2.5+1.0 = 8.5
        score, _ = compute_quality_score(price=30.0, volume=20_000_000, change_pct=10.0, ticker="AAPL")
        assert score == round(8.5 * 10 / 9, 1)

    def test_price_10_to_19(self) -> None:
        # price 10-19 → 1.5; total raw = 1.5+3.0+2.5+1.0 = 8.0
        score, _ = compute_quality_score(price=15.0, volume=20_000_000, change_pct=10.0, ticker="AAPL")
        assert score == round(8.0 * 10 / 9, 1)

    def test_price_below_10_penny_stock(self) -> None:
        # price <10 → 1.0; total raw = 1.0+3.0+2.5+1.0 = 7.5
        score, _ = compute_quality_score(price=5.0, volume=20_000_000, change_pct=10.0, ticker="AAPL")
        assert score == round(7.5 * 10 / 9, 1)

    # ── Volume tier ───────────────────────────────────────────────────────────

    def test_volume_above_20m(self) -> None:
        # vol>=20M → 3.0; raw = 2.5+3.0+2.5+1.0 = 9.0
        score, _ = compute_quality_score(price=100.0, volume=25_000_000, change_pct=10.0, ticker="AAPL")
        assert score == 10.0

    def test_volume_5m_to_20m(self) -> None:
        # vol 5-20M → 2.5; raw = 2.5+2.5+2.5+1.0 = 8.5
        score, _ = compute_quality_score(price=100.0, volume=10_000_000, change_pct=10.0, ticker="AAPL")
        assert score == round(8.5 * 10 / 9, 1)

    def test_volume_2m_to_5m(self) -> None:
        # vol 2-5M → 2.0; raw = 2.5+2.0+2.5+1.0 = 8.0
        score, _ = compute_quality_score(price=100.0, volume=3_000_000, change_pct=10.0, ticker="AAPL")
        assert score == round(8.0 * 10 / 9, 1)

    def test_volume_1m_to_2m(self) -> None:
        # vol 1-2M → 1.5; raw = 2.5+1.5+2.5+1.0 = 7.5
        score, _ = compute_quality_score(price=100.0, volume=1_500_000, change_pct=10.0, ticker="AAPL")
        assert score == round(7.5 * 10 / 9, 1)

    def test_volume_below_1m_lowest_tier(self) -> None:
        # vol <1M → 1.0; raw = 2.5+1.0+2.5+1.0 = 7.0
        score, _ = compute_quality_score(price=100.0, volume=500_000, change_pct=10.0, ticker="AAPL")
        assert score == round(7.0 * 10 / 9, 1)

    # ── Change % tier ─────────────────────────────────────────────────────────

    def test_change_5_to_15_pct_sweet_spot(self) -> None:
        # Sweet spot → 2.5; raw = 2.5+3.0+2.5+1.0 = 9.0 → 10.0
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=10.0, ticker="AAPL")
        assert score == 10.0

    def test_change_at_boundary_5_pct(self) -> None:
        # 5% is included in sweet spot
        score_5, _ = compute_quality_score(100.0, 20_000_000, 5.0, "AAPL")
        score_10, _ = compute_quality_score(100.0, 20_000_000, 10.0, "AAPL")
        assert score_5 == score_10  # Both in sweet spot

    def test_change_15_to_25_pct(self) -> None:
        # change 20% → 2.0; raw = 2.5+3.0+2.0+1.0 = 8.5
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=20.0, ticker="AAPL")
        assert score == round(8.5 * 10 / 9, 1)

    def test_change_25_to_40_pct(self) -> None:
        # change 30% → 1.5; raw = 2.5+3.0+1.5+1.0 = 8.0
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=30.0, ticker="AAPL")
        assert score == round(8.0 * 10 / 9, 1)

    def test_change_40_to_60_pct(self) -> None:
        # change 50% → 1.0; raw = 2.5+3.0+1.0+1.0 = 7.5
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=50.0, ticker="AAPL")
        assert score == round(7.5 * 10 / 9, 1)

    def test_change_above_60_pct_suspicious(self) -> None:
        # change 80% → 0.3 (suspicious/pump); raw = 2.5+3.0+0.3+1.0 = 6.8
        score, _ = compute_quality_score(price=100.0, volume=20_000_000, change_pct=80.0, ticker="AAPL")
        assert score == round(6.8 * 10 / 9, 1)

    # ── Ticker length ─────────────────────────────────────────────────────────

    def test_short_ticker_4_chars_or_less_bonus(self) -> None:
        score_4, _ = compute_quality_score(100.0, 20_000_000, 10.0, "AAPL")
        score_3, _ = compute_quality_score(100.0, 20_000_000, 10.0, "AMD")
        # Both <=4 chars → same contribution
        assert score_4 == score_3

    def test_long_ticker_5_plus_chars_lower_score(self) -> None:
        score_short, _ = compute_quality_score(100.0, 20_000_000, 10.0, "AAPL")  # 4 chars
        score_long, _ = compute_quality_score(100.0, 20_000_000, 10.0, "ABCDE")  # 5 chars
        assert score_short > score_long

    # ── Label assignments ─────────────────────────────────────────────────────

    def test_strong_label_for_high_score(self) -> None:
        # Best-case parameters → Strong
        _, label = compute_quality_score(100.0, 20_000_000, 10.0, "AAPL")
        assert label == "Strong"

    def test_risky_label_for_worst_case(self) -> None:
        # Penny stock, tiny volume, extreme change, long ticker → Risky
        score, label = compute_quality_score(1.0, 100_000, 200.0, "MEMES3")
        # price 1.0, vol 1.0, change 0.3, ticker (>4) 0.5 = raw 2.8 → normalized ≈ 3.1
        assert label == "Risky"
        assert score < 3.5

    def test_watch_label_for_low_mid_quality(self) -> None:
        # price $12 (1.5), vol 800K (1.0), change 80% (0.3), long ticker (0.5) = raw 3.3
        # normalized = round(3.3*10/9, 1) = 3.7 → Watch
        score, label = compute_quality_score(12.0, 800_000, 80.0, "MEMES")
        assert label == "Watch"

    def test_moderate_label_for_mid_quality(self) -> None:
        # price $25 (2.0), vol 1.5M (1.5), change 20% (2.0), ticker 5 chars (0.5) = raw 6.0
        # normalized = round(6.0*10/9, 1) = 6.7 → Moderate
        score, label = compute_quality_score(25.0, 1_500_000, 20.0, "ABCDE")
        assert label == "Moderate"
        assert 5.5 <= score < 7.5

    def test_score_never_exceeds_10(self) -> None:
        # Even with extreme inputs, cap at 10
        score, _ = compute_quality_score(10_000.0, 500_000_000, 10.0, "A")
        assert score <= 10.0

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_tuple_float_and_string(self) -> None:
        result = compute_quality_score(100.0, 20_000_000, 10.0, "AAPL")
        assert isinstance(result, tuple)
        assert len(result) == 2
        score, label = result
        assert isinstance(score, float)
        assert isinstance(label, str)

    def test_label_is_one_of_four_valid_values(self) -> None:
        valid = {"Strong", "Moderate", "Watch", "Risky"}
        for price in [5.0, 15.0, 30.0, 100.0]:
            for volume in [500_000, 2_000_000, 10_000_000, 25_000_000]:
                for change in [5.0, 20.0, 50.0, 100.0]:
                    _, label = compute_quality_score(price, volume, change, "TEST")
                    assert label in valid, f"Unexpected label {label!r} for price={price}, vol={volume}, change={change}"


class TestStockGainerSchema:
    """Tests for StockGainer model validation."""

    def test_negative_change_pct_raises_validation_error(self) -> None:
        with pytest.raises(Exception):  # pydantic ValidationError
            StockGainer(
                ticker="BAD",
                name="Bad Stock",
                market="us",
                price=10.0,
                change_pct=-5.0,
                change_abs=-0.5,
                volume=1_000_000,
            )

    def test_zero_change_pct_does_not_raise(self) -> None:
        # 0% is technically not a gainer but the validator allows it (>= 0)
        g = StockGainer(
            ticker="FLAT",
            name="Flat Stock",
            market="us",
            price=10.0,
            change_pct=0.0,
            change_abs=0.0,
            volume=1_000_000,
        )
        assert g.change_pct == 0.0

    def test_change_pct_rounded_to_2_decimal_places(self) -> None:
        g = StockGainer(
            ticker="TEST",
            name="Test",
            market="us",
            price=10.0,
            change_pct=8.5678,
            change_abs=0.85,
            volume=1_000_000,
        )
        assert g.change_pct == 8.57

    def test_quality_fields_default_to_none(self) -> None:
        g = StockGainer(
            ticker="TEST",
            name="Test",
            market="us",
            price=10.0,
            change_pct=5.0,
            change_abs=0.5,
            volume=1_000_000,
        )
        assert g.quality_score is None
        assert g.quality_label is None

    def test_quality_fields_accepted_when_set(self) -> None:
        g = StockGainer(
            ticker="NVDA",
            name="NVIDIA",
            market="us",
            price=900.0,
            change_pct=8.5,
            change_abs=74.5,
            volume=45_000_000,
            quality_score=9.8,
            quality_label="Strong",
        )
        assert g.quality_score == 9.8
        assert g.quality_label == "Strong"

    def test_valid_quality_labels_accepted(self) -> None:
        for label in ("Strong", "Moderate", "Watch", "Risky"):
            g = StockGainer(
                ticker="TEST",
                name="Test",
                market="us",
                price=10.0,
                change_pct=5.0,
                change_abs=0.5,
                volume=1_000_000,
                quality_label=label,  # type: ignore[arg-type]
            )
            assert g.quality_label == label

    def test_optional_fields_default_to_none(self) -> None:
        g = StockGainer(
            ticker="X",
            name="X Corp",
            market="india",
            price=100.0,
            change_pct=5.0,
            change_abs=5.0,
            volume=1_000_000,
        )
        assert g.avg_volume is None
        assert g.market_cap is None
        assert g.sector is None
        assert g.industry is None


class TestGainerAnalysisSchema:
    """Tests for GainerAnalysis model, focusing on the new related_beneficiaries fields."""

    def test_related_beneficiaries_defaults_to_empty_list(self) -> None:
        analysis = GainerAnalysis(
            ticker="NVDA",
            why_it_gained="Earnings beat",
            key_catalysts=["Beat estimates"],
            catalyst_type="earnings",
            sentiment="very_positive",
            is_sustained=True,
            sustainability_reason="Structural demand",
            confidence=0.8,
        )
        assert analysis.related_beneficiaries == []

    def test_beneficiary_reasoning_defaults_to_none(self) -> None:
        analysis = GainerAnalysis(
            ticker="NVDA",
            why_it_gained="Earnings beat",
            key_catalysts=["Beat estimates"],
            catalyst_type="earnings",
            sentiment="very_positive",
            is_sustained=True,
            sustainability_reason="Structural demand",
            confidence=0.8,
        )
        assert analysis.beneficiary_reasoning is None

    def test_related_beneficiaries_populated_correctly(self) -> None:
        analysis = GainerAnalysis(
            ticker="NVDA",
            why_it_gained="Earnings beat",
            key_catalysts=["Beat estimates"],
            catalyst_type="earnings",
            sentiment="very_positive",
            is_sustained=True,
            sustainability_reason="Structural demand",
            confidence=0.8,
            related_beneficiaries=["AMD", "AVGO", "SMCI"],
            beneficiary_reasoning="Same semiconductor supply chain benefits.",
        )
        assert analysis.related_beneficiaries == ["AMD", "AVGO", "SMCI"]
        assert "semiconductor" in (analysis.beneficiary_reasoning or "").lower()

    def test_confidence_above_1_raises_validation_error(self) -> None:
        with pytest.raises(Exception):
            GainerAnalysis(
                ticker="NVDA",
                why_it_gained="Test",
                key_catalysts=[],
                catalyst_type="unknown",
                sentiment="neutral",
                is_sustained=False,
                sustainability_reason="n/a",
                confidence=1.5,  # Invalid: must be <= 1.0
            )

    def test_confidence_below_0_raises_validation_error(self) -> None:
        with pytest.raises(Exception):
            GainerAnalysis(
                ticker="NVDA",
                why_it_gained="Test",
                key_catalysts=[],
                catalyst_type="unknown",
                sentiment="neutral",
                is_sustained=False,
                sustainability_reason="n/a",
                confidence=-0.1,  # Invalid: must be >= 0.0
            )

    def test_confidence_at_boundaries_accepted(self) -> None:
        for confidence in (0.0, 1.0):
            analysis = GainerAnalysis(
                ticker="T",
                why_it_gained="Test",
                key_catalysts=["x"],
                catalyst_type="unknown",
                sentiment="neutral",
                is_sustained=False,
                sustainability_reason="n/a",
                confidence=confidence,
            )
            assert analysis.confidence == confidence


class TestMarketSummarySchema:
    """Tests for the MarketSummary model added for AI market narrative."""

    def test_valid_market_summary_us(self) -> None:
        summary = MarketSummary(
            market="us",
            narrative="AI demand is driving tech sector gains.",
            themes=["AI infrastructure", "Semiconductors"],
            dominant_sector="Technology",
            sentiment="bullish",
            watch_list=["AMD", "SMCI"],
            watch_reason="May follow NVDA's lead in 1-3 sessions.",
        )
        assert summary.market == "us"
        assert summary.sentiment == "bullish"
        assert len(summary.themes) == 2
        assert summary.from_cache is False

    def test_valid_market_summary_india(self) -> None:
        summary = MarketSummary(
            market="india",
            narrative="IT services exports driving NSE rally.",
            themes=["IT services", "Rupee strength"],
            sentiment="mixed",
            watch_list=["TCS", "INFY"],
            watch_reason="Earnings season approaching.",
        )
        assert summary.market == "india"

    def test_invalid_sentiment_raises(self) -> None:
        with pytest.raises(Exception):
            MarketSummary(
                market="us",
                narrative="Test",
                themes=[],
                sentiment="super_bullish",  # Not a valid enum value
                watch_list=[],
                watch_reason="test",
            )

    def test_all_valid_sentiment_values(self) -> None:
        for sentiment in ("very_bullish", "bullish", "mixed", "bearish", "very_bearish"):
            summary = MarketSummary(
                market="us",
                narrative="Test",
                themes=[],
                sentiment=sentiment,  # type: ignore[arg-type]
                watch_list=[],
                watch_reason="test",
            )
            assert summary.sentiment == sentiment

    def test_from_cache_defaults_false(self) -> None:
        summary = MarketSummary(
            market="us",
            narrative="Test",
            themes=[],
            sentiment="mixed",
            watch_list=[],
            watch_reason="N/A",
        )
        assert summary.from_cache is False

    def test_from_cache_can_be_set_true(self) -> None:
        summary = MarketSummary(
            market="us",
            narrative="Test",
            themes=[],
            sentiment="mixed",
            watch_list=[],
            watch_reason="N/A",
            from_cache=True,
        )
        assert summary.from_cache is True

    def test_dominant_sector_is_optional(self) -> None:
        summary = MarketSummary(
            market="us",
            narrative="No clear sector leader today.",
            themes=["Broad market rally"],
            sentiment="mixed",
            watch_list=[],
            watch_reason="N/A",
        )
        assert summary.dominant_sector is None

    def test_watch_list_can_be_empty(self) -> None:
        summary = MarketSummary(
            market="us",
            narrative="Nothing standout.",
            themes=["Low conviction day"],
            sentiment="mixed",
            watch_list=[],
            watch_reason="No specific follow-through expected.",
        )
        assert summary.watch_list == []
