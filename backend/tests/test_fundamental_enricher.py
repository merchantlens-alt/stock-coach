from __future__ import annotations

"""
Tests for services/fundamental_enricher.py

All yfinance calls are mocked — no real network calls ever made.
Coverage target: every branch in enricher helpers + integration path.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from models.schemas import FundamentalsData, PeerComparison
from services.fundamental_enricher import (
    FundamentalEnricher,
    _safe_float,
    compute_cagr,
    compute_overall_valuation,
    compute_valuation_signal,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_financials(
    revenue: list[float] | None = None,
    net_income: list[float] | None = None,
    ebit: list[float] | None = None,
    interest: list[float] | None = None,
) -> pd.DataFrame:
    """
    Build a fake yfinance financials DataFrame.
    Columns = dates (most recent first), rows = metrics.
    Values are in units of 1 (not millions) to keep tests simple.
    """
    years = 5
    dates = pd.date_range(end="2024-12-31", periods=years, freq="YE")[::-1]

    data: dict[str, list[float]] = {}
    if revenue is not None:
        data["Total Revenue"] = revenue + [0.0] * (years - len(revenue))
    if net_income is not None:
        data["Net Income"] = net_income + [0.0] * (years - len(net_income))
    if ebit is not None:
        data["EBIT"] = ebit + [0.0] * (years - len(ebit))
    if interest is not None:
        data["Interest Expense"] = interest + [0.0] * (years - len(interest))

    df = pd.DataFrame(data, index=dates).T
    # Ensure most-recent date is the first column
    df = df[sorted(df.columns, reverse=True)]
    return df


def _make_balance_sheet(
    total_debt: list[float] | None = None,
    equity: list[float] | None = None,
    current_assets: list[float] | None = None,
    current_liabilities: list[float] | None = None,
) -> pd.DataFrame:
    years = 5
    dates = pd.date_range(end="2024-12-31", periods=years, freq="YE")[::-1]

    data: dict[str, list[float]] = {}
    if total_debt is not None:
        data["Total Debt"] = total_debt + [0.0] * (years - len(total_debt))
    if equity is not None:
        data["Stockholders Equity"] = equity + [0.0] * (years - len(equity))
    if current_assets is not None:
        data["Current Assets"] = current_assets + [0.0] * (years - len(current_assets))
    if current_liabilities is not None:
        data["Current Liabilities"] = current_liabilities + [0.0] * (years - len(current_liabilities))

    df = pd.DataFrame(data, index=dates).T
    df = df[sorted(df.columns, reverse=True)]
    return df


def _make_cashflow(
    ocf: list[float] | None = None,
    capex: list[float] | None = None,
) -> pd.DataFrame:
    years = 4
    dates = pd.date_range(end="2024-12-31", periods=years, freq="YE")[::-1]

    data: dict[str, list[float]] = {}
    if ocf is not None:
        data["Operating Cash Flow"] = ocf + [0.0] * (years - len(ocf))
    if capex is not None:
        data["Capital Expenditure"] = capex + [0.0] * (years - len(capex))

    df = pd.DataFrame(data, index=dates).T
    df = df[sorted(df.columns, reverse=True)]
    return df


def _make_info(
    pe: float | None = 25.0,
    pb: float | None = 4.0,
    ev_ebitda: float | None = 15.0,
    total_assets: float | None = 500_000_000,
    current_liabilities: float | None = 100_000_000,
    total_debt: float | None = 50_000_000,
    equity: float | None = 200_000_000,
    roe: float | None = 0.20,
    revenue_growth: float | None = 0.15,
) -> dict:
    return {
        "trailingPE": pe,
        "priceToBook": pb,
        "enterpriseToEbitda": ev_ebitda,
        "totalAssets": total_assets,
        "totalCurrentLiabilities": current_liabilities,
        "totalDebt": total_debt,
        "totalStockholderEquity": equity,
        "returnOnEquity": roe,
        "revenueGrowth": revenue_growth,
        "longName": "Test Corp",
    }


def _make_price_history() -> pd.DataFrame:
    """12 months of fake monthly prices."""
    dates = pd.date_range(end="2024-12-31", periods=12, freq="ME")
    df = pd.DataFrame({"Close": [100.0] * 12}, index=dates)
    return df


def _make_ticker_mock(
    info: dict | None = None,
    fin: pd.DataFrame | None = None,
    bal: pd.DataFrame | None = None,
    cf: pd.DataFrame | None = None,
    hist: pd.DataFrame | None = None,
) -> MagicMock:
    m = MagicMock()
    m.info = info or _make_info()
    m.financials = fin if fin is not None else _make_financials(
        revenue=[1_000, 800, 650, 550, 450],
        net_income=[100, 80, 65, 55, 45],
        ebit=[130, 110, 90, 80, 70],
        interest=[-20, -18, -16, -14, -12],
    )
    m.balance_sheet = bal if bal is not None else _make_balance_sheet(
        total_debt=[100, 120, 140, 150, 160],
        equity=[400, 350, 310, 280, 260],
        current_assets=[300, 280, 250, 220, 200],
        current_liabilities=[150, 140, 130, 120, 110],
    )
    m.cashflow = cf if cf is not None else _make_cashflow(
        ocf=[120_000_000, 100_000_000, 90_000_000, 80_000_000],
        capex=[-30_000_000, -25_000_000, -20_000_000, -18_000_000],
    )
    m.history = MagicMock(return_value=hist if hist is not None else _make_price_history())
    return m


# ── Unit tests: pure helpers ──────────────────────────────────────────────────

class TestSafeFloat:
    def test_int(self):
        assert _safe_float(5) == 5.0

    def test_float(self):
        assert _safe_float(3.14) == 3.14

    def test_string_number(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        import math
        assert _safe_float(float("nan")) is None

    def test_invalid_string(self):
        assert _safe_float("N/A") is None

    def test_zero(self):
        assert _safe_float(0) == 0.0


class TestComputeCagr:
    def test_positive_growth(self):
        # 100 → 133.1 over 3 years = 10% CAGR
        result = compute_cagr(start=100, end=133.1, years=3)
        assert result is not None
        assert abs(result - 0.10) < 0.001

    def test_negative_growth(self):
        result = compute_cagr(start=100, end=80, years=2)
        assert result is not None
        assert result < 0

    def test_zero_start_returns_none(self):
        assert compute_cagr(0, 100, 3) is None

    def test_negative_start_returns_none(self):
        assert compute_cagr(-50, 100, 3) is None

    def test_zero_end_returns_none(self):
        assert compute_cagr(100, 0, 3) is None

    def test_zero_years_returns_none(self):
        assert compute_cagr(100, 200, 0) is None

    def test_one_year(self):
        result = compute_cagr(100, 115, 1)
        assert result is not None
        assert abs(result - 0.15) < 0.001


class TestComputeValuationSignal:
    def test_cheap_vs_both(self):
        # current = 10, sector = 20, hist = 18  → both above by >10%
        assert compute_valuation_signal(10.0, 20.0, 18.0) == "cheap"

    def test_expensive_vs_both(self):
        # current = 40, sector = 20, hist = 22
        assert compute_valuation_signal(40.0, 20.0, 22.0) == "expensive"

    def test_fair_when_mixed(self):
        # cheap vs sector, expensive vs history → fair
        assert compute_valuation_signal(10.0, 20.0, 8.0) == "fair"

    def test_fair_within_band(self):
        # within ±10% of both
        assert compute_valuation_signal(20.0, 21.0, 19.5) == "fair"

    def test_none_current_returns_none(self):
        assert compute_valuation_signal(None, 20.0, 18.0) is None

    def test_none_both_benchmarks_returns_none(self):
        assert compute_valuation_signal(20.0, None, None) is None

    def test_only_sector_avg_cheap(self):
        # Only one benchmark: < 0.9 → cheap
        assert compute_valuation_signal(10.0, 20.0, None) == "cheap"

    def test_only_sector_avg_expensive(self):
        assert compute_valuation_signal(30.0, 15.0, None) == "expensive"

    def test_zero_benchmark_ignored(self):
        # Zero benchmark should be skipped
        assert compute_valuation_signal(10.0, 0.0, None) is None


class TestComputeOverallValuation:
    def test_two_cheap(self):
        assert compute_overall_valuation(["cheap", "cheap", "fair"]) == "undervalued"

    def test_two_expensive(self):
        assert compute_overall_valuation(["expensive", "expensive", None]) == "overvalued"

    def test_mixed(self):
        assert compute_overall_valuation(["cheap", "expensive", "fair"]) == "mixed"

    def test_all_fair(self):
        assert compute_overall_valuation(["fair", "fair", "fair"]) == "fairly_valued"

    def test_all_none(self):
        assert compute_overall_valuation([None, None, None]) is None

    def test_empty(self):
        assert compute_overall_valuation([]) is None

    def test_single_cheap(self):
        # Only 1 vote, cheap but less than 2 → fairly_valued
        assert compute_overall_valuation(["cheap", None]) == "fairly_valued"

    def test_three_cheap(self):
        assert compute_overall_valuation(["cheap", "cheap", "cheap"]) == "undervalued"


# ── Unit tests: FundamentalEnricher helpers ───────────────────────────────────

class TestEnricherHelpers:
    """Tests for the internal helper methods of FundamentalEnricher."""

    def setup_method(self) -> None:
        self.e = FundamentalEnricher()

    def test_annual_series_extracts_values(self):
        fin = _make_financials(revenue=[1000, 800, 600, 400, 200])
        result = self.e._annual_series(fin, "Total Revenue")
        assert len(result) == 5
        assert result[0] == 1000  # most recent first

    def test_annual_series_fallback_name(self):
        """Uses second name when first is not in index."""
        fin = _make_financials(net_income=[100, 80, 60, 40, 20])
        result = self.e._annual_series(fin, "NonExistent", "Net Income")
        assert result[0] == 100

    def test_annual_series_none_df(self):
        assert self.e._annual_series(None, "Total Revenue") == []

    def test_annual_series_missing_key(self):
        fin = _make_financials(revenue=[100])
        assert self.e._annual_series(fin, "Nonexistent") == []

    def test_cagr_from_series_3y(self):
        series = [1331, 1200, 1100, 1000]  # most recent first
        result = self.e._cagr_from_series(series, 3)
        # 1000 → 1331 over 3 years = 10% CAGR
        assert result is not None
        assert abs(result - 0.10) < 0.001

    def test_cagr_from_series_clamps_to_available_data(self):
        series = [120, 100]       # only 2 points → 1-year CAGR
        result = self.e._cagr_from_series(series, 5)
        assert result is not None
        assert abs(result - 0.20) < 0.001

    def test_cagr_from_series_empty(self):
        assert self.e._cagr_from_series([], 3) is None

    def test_cagr_from_series_single_point(self):
        assert self.e._cagr_from_series([100], 3) is None

    def test_roe_history(self):
        fin = _make_financials(net_income=[100, 80, 60])
        bal = _make_balance_sheet(equity=[500, 400, 300])
        roe = self.e._roe_history(fin, bal)
        assert len(roe) == 3
        assert abs(roe[0] - 0.20) < 0.001  # 100/500

    def test_roe_history_skips_zero_equity(self):
        fin = _make_financials(net_income=[100, 80])
        bal = _make_balance_sheet(equity=[500, 0])   # second year equity = 0
        roe = self.e._roe_history(fin, bal)
        assert len(roe) == 1   # only first year valid

    def test_roe_history_missing_data(self):
        assert self.e._roe_history(None, None) == []

    def test_roce(self):
        fin = _make_financials(ebit=[200])
        info = _make_info(total_assets=1_000_000, current_liabilities=200_000)
        result = self.e._roce(info, fin, None)
        # ROCE = 200 / (1_000_000 - 200_000) = 200 / 800_000 ≈ 0.00025
        assert result is not None
        assert result > 0

    def test_roce_zero_capital_employed(self):
        fin = _make_financials(ebit=[200])
        info = _make_info(total_assets=100_000, current_liabilities=100_000)
        assert self.e._roce(info, fin, None) is None

    def test_roce_missing_info(self):
        fin = _make_financials(ebit=[200])
        assert self.e._roce({}, fin, None) is None

    def test_interest_coverage(self):
        fin = _make_financials(ebit=[130], interest=[-20])
        result = self.e._interest_coverage(fin)
        assert result is not None
        assert abs(result - 6.5) < 0.01  # 130 / 20

    def test_interest_coverage_zero_interest(self):
        fin = _make_financials(ebit=[130], interest=[0])
        assert self.e._interest_coverage(fin) is None

    def test_interest_coverage_missing_data(self):
        assert self.e._interest_coverage(None) is None

    def test_current_ratio(self):
        bal = _make_balance_sheet(current_assets=[300], current_liabilities=[150])
        result = self.e._current_ratio(bal)
        assert result == 2.0

    def test_current_ratio_zero_liabilities(self):
        bal = _make_balance_sheet(current_assets=[300], current_liabilities=[0])
        assert self.e._current_ratio(bal) is None

    def test_current_ratio_missing_data(self):
        assert self.e._current_ratio(None) is None

    def test_fcf_growing(self):
        # OCF growing, CAPEX stable
        cf = _make_cashflow(
            ocf=[150_000_000, 100_000_000],
            capex=[-20_000_000, -20_000_000],
        )
        fcf, trend = self.e._fcf(cf)
        assert fcf is not None
        assert fcf > 0
        assert trend == "growing"

    def test_fcf_declining(self):
        cf = _make_cashflow(
            ocf=[50_000_000, 100_000_000],
            capex=[-10_000_000, -10_000_000],
        )
        fcf, trend = self.e._fcf(cf)
        assert trend == "declining"

    def test_fcf_stable(self):
        cf = _make_cashflow(
            ocf=[100_000_000, 100_000_000],
            capex=[-10_000_000, -10_000_000],
        )
        _, trend = self.e._fcf(cf)
        assert trend == "stable"

    def test_fcf_no_data(self):
        fcf, trend = self.e._fcf(None)
        assert fcf is None
        assert trend is None

    def test_de_trend_falling(self):
        # D/E: recent 0.25, old 0.62 → falling
        bal = _make_balance_sheet(
            total_debt=[100, 150, 160],
            equity=[400, 300, 260],
        )
        assert self.e._de_trend(bal) == "falling"

    def test_de_trend_rising(self):
        bal = _make_balance_sheet(
            total_debt=[400, 150, 100],
            equity=[400, 400, 400],
        )
        assert self.e._de_trend(bal) == "rising"

    def test_de_trend_stable(self):
        bal = _make_balance_sheet(
            total_debt=[100, 102, 99],
            equity=[400, 400, 400],
        )
        assert self.e._de_trend(bal) == "stable"

    def test_de_trend_insufficient_data(self):
        bal = _make_balance_sheet(total_debt=[100], equity=[400])
        assert self.e._de_trend(bal) is None

    def test_de_from_info(self):
        info = {"totalDebt": 200_000_000, "totalStockholderEquity": 400_000_000}
        result = FundamentalEnricher._de_from_info(info)
        assert result == 0.50

    def test_de_from_info_zero_equity(self):
        info = {"totalDebt": 200_000_000, "totalStockholderEquity": 0}
        assert FundamentalEnricher._de_from_info(info) is None

    def test_de_from_info_missing(self):
        assert FundamentalEnricher._de_from_info({}) is None


# ── Integration tests: FundamentalEnricher.enrich() ──────────────────────────

class TestFundamentalEnricherIntegration:

    def setup_method(self) -> None:
        self.enricher = FundamentalEnricher()

    def _run(self, coro):
        return asyncio.run(coro)

    def _make_mock_ticker(self, **kwargs):
        return _make_ticker_mock(**kwargs)

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_happy_path_us_stock(self, mock_ticker_cls):
        """Enrich() with all data available returns fully populated FundamentalsData."""
        ticker_mock = _make_ticker_mock()
        mock_ticker_cls.return_value = ticker_mock

        result = self._run(self.enricher.enrich("AAPL", "us"))

        assert isinstance(result, FundamentalsData)
        # Growth CAGRs
        assert result.revenue_cagr_3y is not None
        assert result.revenue_cagr_5y is not None
        assert result.net_profit_cagr_3y is not None
        # Health
        assert result.interest_coverage is not None
        assert result.current_ratio is not None
        assert result.free_cash_flow is not None
        assert result.fcf_trend in ("growing", "stable", "declining")

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_india_ticker_adds_ns_suffix(self, mock_ticker_cls):
        """India tickers must use .NS suffix when calling yfinance."""
        mock_ticker_cls.return_value = _make_ticker_mock()
        self._run(self.enricher.enrich("TCS", "india"))
        # First call should be with .NS suffix
        first_call_sym = mock_ticker_cls.call_args_list[0][0][0]
        assert first_call_sym == "TCS.NS"

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_peer_map_lookup(self, mock_ticker_cls):
        """Known peers are fetched and returned in the peers list."""
        mock_ticker_cls.return_value = _make_ticker_mock()
        result = self._run(self.enricher.enrich("AAPL", "us"))
        # AAPL peers = MSFT, GOOGL, META → 4 total calls (1 main + 3 peers)
        assert mock_ticker_cls.call_count == 4

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_unknown_ticker_no_peers(self, mock_ticker_cls):
        """Stocks not in peer map still complete, just with no peer data."""
        mock_ticker_cls.return_value = _make_ticker_mock()
        result = self._run(self.enricher.enrich("UNKNOWN123", "us"))
        assert isinstance(result, FundamentalsData)
        assert result.peers is None
        # Only 1 yfinance call (main ticker, no peers)
        assert mock_ticker_cls.call_count == 1

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_yfinance_failure_returns_empty_fundamentals(self, mock_ticker_cls):
        """If yfinance raises for main ticker, returns FundamentalsData with Nones."""
        mock_ticker_cls.side_effect = Exception("network error")
        result = self._run(self.enricher.enrich("AAPL", "us"))
        assert isinstance(result, FundamentalsData)
        assert result.revenue_cagr_3y is None
        assert result.peers is None

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_peer_fetch_failure_is_silently_skipped(self, mock_ticker_cls):
        """If peer yfinance calls fail, main data is still returned correctly."""
        call_count = [0]

        def side_effect(sym):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_ticker_mock()   # main ticker succeeds
            raise Exception("peer error")    # all peer calls fail

        mock_ticker_cls.side_effect = side_effect
        result = self._run(self.enricher.enrich("AAPL", "us"))
        assert isinstance(result, FundamentalsData)
        assert result.revenue_cagr_3y is not None   # main data still populated
        assert result.peers is None                  # no peers due to failures

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_merges_with_existing_fundamentals(self, mock_ticker_cls):
        """New fields are merged with pre-existing basic fundamentals."""
        mock_ticker_cls.return_value = _make_ticker_mock()
        existing = FundamentalsData(
            pe_ratio=25.0,
            roe=0.20,
            analyst_recommendation="buy",
        )
        result = self._run(self.enricher.enrich("AAPL", "us", existing=existing))
        # Original fields preserved
        assert result.pe_ratio == 25.0
        assert result.roe == 0.20
        assert result.analyst_recommendation == "buy"
        # New fields added
        assert result.revenue_cagr_3y is not None

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_valuation_signals_computed(self, mock_ticker_cls):
        """Valuation signals are set when peer PE data is available."""
        peer_mock = _make_ticker_mock(info=_make_info(pe=20.0, pb=3.0))
        call_count = [0]

        def side_effect(sym):
            call_count[0] += 1
            return peer_mock

        mock_ticker_cls.side_effect = side_effect
        result = self._run(self.enricher.enrich("AAPL", "us"))
        # Valuation classification should be set when we have peer data
        assert result.valuation_classification in (
            "undervalued", "fairly_valued", "overvalued", "mixed", None
        )

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_peers_returned_as_peer_comparison_list(self, mock_ticker_cls):
        """Peer rows are deserialized into PeerComparison objects."""
        mock_ticker_cls.return_value = _make_ticker_mock()
        result = self._run(self.enricher.enrich("AAPL", "us"))
        if result.peers:
            assert all(isinstance(p, PeerComparison) for p in result.peers)
            # Ticker should not have .NS suffix
            for p in result.peers:
                assert not p.ticker.endswith(".NS")

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_empty_financials_df_handled(self, mock_ticker_cls):
        """Empty DataFrames don't crash — CAGRs return None."""
        mock = _make_ticker_mock(
            fin=pd.DataFrame(),
            bal=pd.DataFrame(),
            cf=pd.DataFrame(),
        )
        mock_ticker_cls.return_value = mock
        result = self._run(self.enricher.enrich("AAPL", "us"))
        assert result.revenue_cagr_3y is None
        assert result.net_profit_cagr_3y is None
        assert result.interest_coverage is None
        assert result.current_ratio is None

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_fcf_converted_to_millions(self, mock_ticker_cls):
        """FCF is stored in millions (divides raw yfinance units by 1_000_000)."""
        cf = _make_cashflow(
            ocf=[500_000_000, 400_000_000],   # 500M, 400M
            capex=[-50_000_000, -40_000_000],
        )
        mock = _make_ticker_mock(cf=cf)
        mock_ticker_cls.return_value = mock
        result = self._run(self.enricher.enrich("AAPL", "us"))
        # FCF = (500M - 50M) / 1M = 450
        assert result.free_cash_flow is not None
        assert abs(result.free_cash_flow - 450.0) < 1.0

    @patch("services.fundamental_enricher.yf.Ticker")
    def test_de_trend_falling_reflected_in_result(self, mock_ticker_cls):
        """D/E trend is correctly propagated to result."""
        bal = _make_balance_sheet(
            total_debt=[100, 200, 250],
            equity=[400, 350, 300],
        )
        mock = _make_ticker_mock(bal=bal)
        mock_ticker_cls.return_value = mock
        result = self._run(self.enricher.enrich("AAPL", "us"))
        assert result.de_5y_trend == "falling"
