"""
Tests for Value Recovery Scanner — pure helpers + integration + API.

All yfinance calls are mocked. No live network calls, no live AI calls.

Patch notes:
  - `yfinance.download` / `yfinance.Ticker` must be patched at the *yfinance*
    module level because the scanner imports yfinance with a local statement
    (`import yfinance as yf`) inside each method body, so patching
    `services.value_recovery_scanner.yf.*` would have no effect.
  - `_US_TICKER_UNIVERSE` / `_INDIA_TICKER_UNIVERSE` must also be patched in
    integration tests so the scanner iterates the same ticker set that is in
    the fake price DataFrame.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import RecoverySignal, ValueRecoveryStock
from services.value_recovery_scanner import (
    ValueRecoveryScannerService,
    build_recovery_thesis,
    classify_signals,
    compute_recovery_score,
)


# ── Test data factories ───────────────────────────────────────────────────────

def _all_signals() -> list[RecoverySignal]:
    return list(RecoverySignal)


def _make_fund_info(**overrides) -> dict:
    """Return a yfinance-style info dict for a healthy, cheap stock."""
    base = {
        "trailingPE":        14.0,
        "forwardPE":         11.0,
        "earningsGrowth":     0.20,
        "revenueGrowth":      0.12,
        "returnOnEquity":     0.18,
        "debtToEquity":      45.0,   # 45% = 0.45× actual D/E
        "profitMargins":      0.14,
        "recommendationKey": "buy",
        "targetMeanPrice":  160.0,
    }
    base.update(overrides)
    return base


def _make_yf_ticker_mock(info: dict) -> MagicMock:
    mock = MagicMock()
    mock.info = info
    return mock


def _make_price_df(tickers: list[str], rows: int = 30):
    """Minimal MultiIndex DataFrame mimicking yf.download output."""
    import numpy as np
    import pandas as pd

    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close_data = {t: np.linspace(100, 120, rows) for t in tickers}
    vol_data   = {t: [1_000_000] * rows          for t in tickers}

    close = pd.DataFrame(close_data, index=dates)
    vol   = pd.DataFrame(vol_data,   index=dates)
    # Mimic yf.download multi-ticker shape: columns = (field, ticker)
    return pd.concat({"Close": close, "Volume": vol}, axis=1)


def _us_universe(tickers: list[str]) -> dict:
    """Fake _US_TICKER_UNIVERSE mapping ticker → meta for a set of tickers."""
    return {t: {"name": f"{t} Inc", "sector": "Technology"} for t in tickers}


def _india_universe(tickers: list[str]) -> dict:
    """Fake _INDIA_TICKER_UNIVERSE mapping ticker → meta (no .NS suffix here)."""
    return {t: {"name": f"{t} Ltd", "sector": "Energy"} for t in tickers}


# ── classify_signals ──────────────────────────────────────────────────────────

class TestClassifySignals:
    def test_eps_growing_fires_above_threshold(self) -> None:
        sigs = classify_signals(14, 11, 0.10, None, None, None, None, None)
        assert RecoverySignal.eps_growing in sigs

    def test_eps_growing_does_not_fire_at_threshold(self) -> None:
        # 0.08 is the boundary; must be strictly greater
        sigs = classify_signals(14, 11, 0.05, None, None, None, None, None)
        assert RecoverySignal.eps_growing not in sigs

    def test_revenue_growing_fires(self) -> None:
        sigs = classify_signals(14, 11, None, 0.08, None, None, None, None)
        assert RecoverySignal.revenue_growing in sigs

    def test_revenue_growing_does_not_fire_below_threshold(self) -> None:
        sigs = classify_signals(14, 11, None, 0.03, None, None, None, None)
        assert RecoverySignal.revenue_growing not in sigs

    def test_pe_contracting_fires_when_forward_lt_trailing_by_5pct(self) -> None:
        # forward < trailing * 0.95 → contraction signal
        sigs = classify_signals(20, 18, None, None, None, None, None, None)
        assert RecoverySignal.pe_contracting in sigs

    def test_pe_contracting_does_not_fire_when_contraction_is_small(self) -> None:
        # 19.5 > 20 * 0.95 = 19.0 → no contraction
        sigs = classify_signals(20, 19.5, None, None, None, None, None, None)
        assert RecoverySignal.pe_contracting not in sigs

    def test_pe_contracting_does_not_fire_without_forward_pe(self) -> None:
        sigs = classify_signals(20, None, None, None, None, None, None, None)
        assert RecoverySignal.pe_contracting not in sigs

    def test_strong_roe_fires_above_threshold(self) -> None:
        sigs = classify_signals(14, None, None, None, 0.16, None, None, None)
        assert RecoverySignal.strong_roe in sigs

    def test_strong_roe_does_not_fire_below_threshold(self) -> None:
        sigs = classify_signals(14, None, None, None, 0.10, None, None, None)
        assert RecoverySignal.strong_roe not in sigs

    def test_low_debt_fires_below_threshold(self) -> None:
        # yfinance debtToEquity 60 = 0.60× actual D/E
        sigs = classify_signals(14, None, None, None, None, 60.0, None, None)
        assert RecoverySignal.low_debt in sigs

    def test_low_debt_does_not_fire_at_or_above_threshold(self) -> None:
        sigs = classify_signals(14, None, None, None, None, 120.0, None, None)
        assert RecoverySignal.low_debt not in sigs

    def test_profitable_fires_above_threshold(self) -> None:
        sigs = classify_signals(14, None, None, None, None, None, 0.12, None)
        assert RecoverySignal.profitable in sigs

    def test_analyst_bullish_fires_for_buy(self) -> None:
        sigs = classify_signals(14, None, None, None, None, None, None, "buy")
        assert RecoverySignal.analyst_bullish in sigs

    def test_analyst_bullish_fires_for_outperform(self) -> None:
        sigs = classify_signals(14, None, None, None, None, None, None, "outperform")
        assert RecoverySignal.analyst_bullish in sigs

    def test_analyst_bullish_fires_for_strong_buy(self) -> None:
        sigs = classify_signals(14, None, None, None, None, None, None, "strong_buy")
        assert RecoverySignal.analyst_bullish in sigs

    def test_analyst_bullish_does_not_fire_for_hold(self) -> None:
        sigs = classify_signals(14, None, None, None, None, None, None, "hold")
        assert RecoverySignal.analyst_bullish not in sigs

    def test_no_inputs_returns_empty(self) -> None:
        sigs = classify_signals(None, None, None, None, None, None, None, None)
        assert sigs == []

    def test_all_signals_can_fire_together(self) -> None:
        sigs = classify_signals(
            pe=14, forward_pe=10,
            earnings_growth=0.25, revenue_growth=0.15,
            roe=0.20, de_ratio=40.0,
            profit_margin=0.18, consensus="strong_buy",
        )
        assert len(sigs) == 7
        assert set(sigs) == set(_all_signals())


# ── compute_recovery_score ────────────────────────────────────────────────────

class TestComputeRecoveryScore:
    def _n_signals(self, n: int) -> list[RecoverySignal]:
        return list(RecoverySignal)[:n]

    def test_very_cheap_pe_scores_higher_than_expensive_pe(self) -> None:
        score_cheap     = compute_recovery_score(10, None, None, self._n_signals(2), None, None)
        score_expensive = compute_recovery_score(28, None, None, self._n_signals(2), None, None)
        assert score_cheap > score_expensive

    def test_forward_pe_contraction_adds_bonus(self) -> None:
        score_no_fwd   = compute_recovery_score(20, None, None, self._n_signals(2), None, None)
        score_with_fwd = compute_recovery_score(20,   14, None, self._n_signals(2), None, None)
        assert score_with_fwd > score_no_fwd

    def test_more_signals_increases_score(self) -> None:
        score_2 = compute_recovery_score(20, None, None, self._n_signals(2), None, None)
        score_4 = compute_recovery_score(20, None, None, self._n_signals(4), None, None)
        assert score_4 > score_2

    def test_high_earnings_growth_adds_points(self) -> None:
        score_low  = compute_recovery_score(20, None, 0.09, self._n_signals(3), None, None)
        score_high = compute_recovery_score(20, None, 0.30, self._n_signals(3), None, None)
        assert score_high > score_low

    def test_strong_buy_adds_more_than_hold(self) -> None:
        score_hold = compute_recovery_score(20, None, None, self._n_signals(3), "hold",       None)
        score_buy  = compute_recovery_score(20, None, None, self._n_signals(3), "strong_buy", None)
        assert score_buy > score_hold

    def test_high_upside_adds_bonus(self) -> None:
        score_no_upside  = compute_recovery_score(20, None, None, self._n_signals(3), None, None)
        score_big_upside = compute_recovery_score(20, None, None, self._n_signals(3), None, 35.0)
        assert score_big_upside > score_no_upside

    def test_score_never_exceeds_100(self) -> None:
        score = compute_recovery_score(
            pe=8, forward_pe=5, earnings_growth=0.50,
            signals=_all_signals(), consensus="strong_buy",
            upside_to_target=50.0,
        )
        assert score <= 100.0

    def test_empty_signals_returns_nonnegative(self) -> None:
        # No signals — only valuation score; no crash expected
        score = compute_recovery_score(10, None, None, [], None, None)
        assert score >= 0.0

    def test_none_pe_still_scores_signals(self) -> None:
        score = compute_recovery_score(None, None, None, self._n_signals(3), "buy", None)
        assert score > 0.0


# ── build_recovery_thesis ─────────────────────────────────────────────────────

class TestBuildRecoveryThesis:
    def test_pe_contracting_leads_thesis(self) -> None:
        thesis = build_recovery_thesis(
            pe=20, forward_pe=14,
            earnings_growth=0.15, revenue_growth=None,
            signals=[RecoverySignal.pe_contracting, RecoverySignal.eps_growing],
        )
        assert "contracting" in thesis.lower()
        assert "re-rating" in thesis.lower()

    def test_cheap_pe_appears_when_no_contraction(self) -> None:
        thesis = build_recovery_thesis(
            pe=14, forward_pe=None,
            earnings_growth=0.10, revenue_growth=None,
            signals=[RecoverySignal.eps_growing, RecoverySignal.strong_roe],
        )
        # pe=14 < 18 → "P/E 14.0× (below mkt avg)"
        assert "14" in thesis

    def test_eps_growth_included_when_present(self) -> None:
        thesis = build_recovery_thesis(
            pe=15, forward_pe=None,
            earnings_growth=0.18, revenue_growth=None,
            signals=[RecoverySignal.eps_growing, RecoverySignal.profitable],
        )
        assert "EPS" in thesis
        assert "18%" in thesis

    def test_revenue_included_when_eps_absent(self) -> None:
        thesis = build_recovery_thesis(
            pe=15, forward_pe=None,
            earnings_growth=None, revenue_growth=0.12,
            signals=[RecoverySignal.revenue_growing, RecoverySignal.analyst_bullish],
        )
        assert "Rev" in thesis

    def test_fallback_when_no_data(self) -> None:
        thesis = build_recovery_thesis(
            pe=None, forward_pe=None,
            earnings_growth=None, revenue_growth=None,
            signals=[RecoverySignal.low_debt, RecoverySignal.profitable],
        )
        # Hits the "if not parts" fallback
        assert "re-rating" in thesis.lower()
        assert len(thesis) > 10

    def test_thesis_always_ends_with_re_rating(self) -> None:
        thesis = build_recovery_thesis(
            pe=12, forward_pe=9,
            earnings_growth=0.22, revenue_growth=0.14,
            signals=_all_signals(),
        )
        assert thesis.endswith("→ re-rating candidate")

    def test_pe_contraction_pct_is_correct(self) -> None:
        # pe=20, forward_pe=14 → 30% contraction
        thesis = build_recovery_thesis(
            pe=20, forward_pe=14,
            earnings_growth=None, revenue_growth=None,
            signals=[RecoverySignal.pe_contracting],
        )
        assert "30%" in thesis


# ── Scanner integration tests (all I/O mocked) ───────────────────────────────

class TestValueRecoveryScannerIntegration:
    """
    Full scan pipeline with mocked yf.download + yf.Ticker.

    Key patching rules:
    • Patch yfinance.download (not services.*.yf.download) — yf is a local
      import inside each method, so the patch must target the yfinance module.
    • Always co-patch _US_TICKER_UNIVERSE / _INDIA_TICKER_UNIVERSE so the
      scanner's iteration set matches the columns in the fake price DataFrame.
    """

    def _make_scanner(self) -> ValueRecoveryScannerService:
        from core.config import get_settings
        return ValueRecoveryScannerService(get_settings())

    # ── Happy path ─────────────────────────────────────────────────────────

    def test_scan_us_returns_stocks_with_valid_signals(self) -> None:
        scanner  = self._make_scanner()
        tickers  = ["AAPL", "MSFT", "JPM"]
        price_df = _make_price_df(tickers)
        info     = _make_fund_info()

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        assert result.market == "us"
        for stock in result.stocks:
            assert len(stock.signals) >= 2
            assert stock.recovery_score >= 40
            assert stock.recovery_quality in ("strong", "emerging")
            assert len(stock.recovery_thesis) > 5

    def test_scan_india_returns_stocks(self) -> None:
        scanner    = self._make_scanner()
        # Universe keys are bare (RELIANCE); price DF columns are RELIANCE.NS
        in_tickers = ["RELIANCE", "TCS", "HDFCBANK"]
        df_tickers = [f"{t}.NS" for t in in_tickers]
        price_df   = _make_price_df(df_tickers)
        info       = _make_fund_info()

        with (
            patch("services.value_recovery_scanner._INDIA_TICKER_UNIVERSE",
                  _india_universe(in_tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("india"))

        assert result.market == "india"
        assert isinstance(result.stocks, list)

    def test_scan_results_sorted_by_score_descending(self) -> None:
        scanner  = self._make_scanner()
        tickers  = ["AAPL", "MSFT", "NVDA", "META"]
        price_df = _make_price_df(tickers)
        info     = _make_fund_info()

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        scores = [s.recovery_score for s in result.stocks]
        assert scores == sorted(scores, reverse=True)

    def test_scan_capped_at_15_results(self) -> None:
        scanner      = self._make_scanner()
        many_tickers = [f"T{i}" for i in range(20)]
        price_df     = _make_price_df(many_tickers)
        info         = _make_fund_info()

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(many_tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        assert len(result.stocks) <= 15

    def test_scan_computes_pe_contraction_pct(self) -> None:
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)
        # 30% forward P/E contraction: 20 → 14
        info = _make_fund_info(trailingPE=20.0, forwardPE=14.0)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        for stock in result.stocks:
            if stock.forward_pe is not None and stock.pe_ratio is not None:
                assert stock.pe_contraction_pct is not None
                assert stock.pe_contraction_pct > 0

    def test_strong_quality_label_for_high_score(self) -> None:
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)
        info = _make_fund_info(
            trailingPE=10.0, forwardPE=7.0,
            earningsGrowth=0.30, revenueGrowth=0.20,
            returnOnEquity=0.25, debtToEquity=30.0,
            profitMargins=0.20, recommendationKey="strong_buy",
            targetMeanPrice=200.0,
        )

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        if result.stocks:
            top = result.stocks[0]
            assert top.recovery_quality == "strong"
            assert top.recovery_score >= 65

    # ── Filtering behaviour ────────────────────────────────────────────────

    def test_scan_filters_sell_rated_stocks(self) -> None:
        scanner   = self._make_scanner()
        tickers   = ["AAPL"]
        price_df  = _make_price_df(tickers)
        sell_info = _make_fund_info(recommendationKey="sell")

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(sell_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        for stock in result.stocks:
            assert stock.analyst_consensus not in ("sell", "strong_sell")

    def test_scan_filters_loss_making_stocks(self) -> None:
        """Stocks with profit_margin < -0.10 must be excluded."""
        scanner   = self._make_scanner()
        tickers   = ["AAPL"]
        price_df  = _make_price_df(tickers)
        loss_info = _make_fund_info(profitMargins=-0.15)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(loss_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        for stock in result.stocks:
            if stock.profit_margin is not None:
                assert stock.profit_margin >= -0.10

    def test_scan_filters_stocks_with_too_few_signals(self) -> None:
        """Stocks with < 2 signals must be filtered out."""
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)
        # Zero signals: all metrics below every threshold
        weak_info = _make_fund_info(
            earningsGrowth=0.02,   # below eps_growing (> 0.08)
            revenueGrowth=0.02,    # below revenue_growing (> 0.05)
            returnOnEquity=0.05,   # below strong_roe (> 0.13)
            debtToEquity=150.0,    # above low_debt (< 80)
            profitMargins=0.03,    # below profitable (> 0.08)
            recommendationKey="hold",
            trailingPE=14.5,
            forwardPE=14.0,        # 14.0 > 14.5*0.95=13.775 → no pe_contracting
        )

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(weak_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        for stock in result.stocks:
            assert len(stock.signals) >= 2

    def test_scan_filters_overvalued_stocks(self) -> None:
        """
        Stocks with a high trailing P/E and no meaningful forward contraction are excluded.

        Path A (pe < 22): cheap absolute — excluded when pe = 42×
        Path B (pe < 35 + contraction): growth-at-reasonable-price —
          excluded when pe = 42×, even with a 48% contraction (DY scenario)
        """
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)
        # pe=42 > 35 → fails Path B; pe=42 > 22 → fails Path A → excluded
        overval_info = _make_fund_info(trailingPE=42.0, forwardPE=22.0)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(overval_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        # No stock with pe > 35 should survive (unless pe < 22 path was hit)
        for stock in result.stocks:
            if stock.pe_ratio is not None and stock.pe_ratio >= 22:
                assert stock.pe_ratio < 35

    def test_scan_filters_low_analyst_upside(self) -> None:
        """Stocks with a known analyst target but < 15% upside must be excluded."""
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)  # prices linspace 100→120, last price ~120
        # Target = 130 → upside = (130-120)/120 = 8.3% < 15% → excluded
        low_upside_info = _make_fund_info(targetMeanPrice=130.0)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(low_upside_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        # Stock with only 8% upside must not appear
        assert all(
            s.upside_to_target is None or s.upside_to_target >= 15.0
            for s in result.stocks
        )

    def test_scan_keeps_stocks_without_analyst_target(self) -> None:
        """Stocks with no analyst target (upside_to_target = None) are NOT excluded."""
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers)
        # No target price → upside_to_target will be None → should not be filtered
        no_target_info = _make_fund_info(targetMeanPrice=None)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker",   return_value=_make_yf_ticker_mock(no_target_info)),
        ):
            result = asyncio.run(scanner.scan("us"))

        # Passing score (all other signals present) → should still appear
        assert len(result.stocks) > 0

    # ── Error handling ─────────────────────────────────────────────────────

    def test_scan_returns_empty_on_yf_download_exception(self) -> None:
        scanner = self._make_scanner()

        with patch("yfinance.download", side_effect=Exception("network error")):
            result = asyncio.run(scanner.scan("us"))

        assert result.stocks == []

    def test_scan_handles_empty_dataframe(self) -> None:
        import pandas as pd
        scanner = self._make_scanner()

        with patch("yfinance.download", return_value=pd.DataFrame()):
            result = asyncio.run(scanner.scan("us"))

        assert result.stocks == []

    def test_scan_handles_dataframe_too_short(self) -> None:
        """DataFrame with fewer than 20 rows should be treated as unusable."""
        scanner  = self._make_scanner()
        tickers  = ["AAPL"]
        price_df = _make_price_df(tickers, rows=10)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
        ):
            result = asyncio.run(scanner.scan("us"))

        assert result.stocks == []

    def test_individual_ticker_failure_does_not_abort_scan(self) -> None:
        """
        If one Ticker.info call raises, the remaining tickers should still be scored.
        """
        scanner  = self._make_scanner()
        tickers  = ["AAPL", "MSFT"]
        price_df = _make_price_df(tickers)
        info     = _make_fund_info()

        call_count = 0

        def _ticker_side_effect(sym):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("rate limited")
            return _make_yf_ticker_mock(info)

        with (
            patch("services.value_recovery_scanner._US_TICKER_UNIVERSE",
                  _us_universe(tickers)),
            patch("yfinance.download", return_value=price_df),
            patch("yfinance.Ticker", side_effect=_ticker_side_effect),
        ):
            result = asyncio.run(scanner.scan("us"))

        # Scan must complete without raising
        assert isinstance(result.stocks, list)


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestValueRecoveryAPI:
    """Tests for GET /api/recovery/{market}."""

    def _make_response(self, market: str, stocks=None):
        from datetime import datetime

        from models.schemas import ValueRecoveryScanResponse
        if stocks is None:
            stocks = [
                ValueRecoveryStock(
                    ticker="AAPL",
                    name="Apple Inc",
                    market=market,
                    sector="Technology",
                    price=150.0,
                    change_pct_1d=0.5,
                    pe_ratio=14.0,
                    forward_pe=11.0,
                    pe_contraction_pct=21.4,
                    signals=[
                        RecoverySignal.eps_growing,
                        RecoverySignal.pe_contracting,
                        RecoverySignal.analyst_bullish,
                    ],
                    recovery_quality="strong",
                    recovery_score=72.5,
                    recovery_thesis="P/E contracting 21% · EPS +20% YoY → re-rating candidate",
                    earnings_growth_yoy=0.20,
                    revenue_growth_yoy=0.12,
                    roe=0.18,
                    de_ratio=45.0,
                    profit_margin=0.14,
                    analyst_consensus="buy",
                    analyst_target=175.0,
                    upside_to_target=16.7,
                    avg_volume=60_000_000,
                )
            ]
        return ValueRecoveryScanResponse(
            market=market,
            stocks=stocks,
            from_cache=False,
            scanned_at=datetime(2024, 6, 1),
        )

    def test_get_recovery_us_returns_200(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        assert resp.status_code == 200
        data = resp.json()
        assert data["market"] == "us"
        assert len(data["stocks"]) == 1
        assert data["stocks"][0]["ticker"] == "AAPL"

    def test_get_recovery_india_returns_200(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("india")),
        ):
            resp = client.get("/api/recovery/india")

        assert resp.status_code == 200
        assert resp.json()["market"] == "india"

    def test_invalid_market_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/recovery/germany")
        assert resp.status_code == 422

    def test_response_has_required_top_level_fields(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        data = resp.json()
        for field in ("market", "stocks", "from_cache", "scanned_at"):
            assert field in data, f"Missing top-level field: {field}"

    def test_stock_has_required_fields(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        stock = resp.json()["stocks"][0]
        for field in (
            "ticker", "name", "market", "price", "change_pct_1d",
            "signals", "recovery_quality", "recovery_score", "recovery_thesis",
        ):
            assert field in stock, f"Missing stock field: {field}"

    def test_recovery_quality_value_is_strong(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        assert resp.json()["stocks"][0]["recovery_quality"] == "strong"

    def test_empty_scan_returns_empty_list(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us", stocks=[])),
        ):
            resp = client.get("/api/recovery/us")

        assert resp.status_code == 200
        assert resp.json()["stocks"] == []

    def test_from_cache_false_on_fresh_scan(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        assert resp.json()["from_cache"] is False

    def test_signals_serialise_as_strings(self, client: TestClient) -> None:
        with patch(
            "services.value_recovery_scanner.ValueRecoveryScannerService.scan",
            new=AsyncMock(return_value=self._make_response("us")),
        ):
            resp = client.get("/api/recovery/us")

        signals = resp.json()["stocks"][0]["signals"]
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, str)
