from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.config import get_settings
from models.schemas import StockGainer
from services.market_data import MarketDataService, _safe_float, _safe_int


@pytest.fixture
def service() -> MarketDataService:
    get_settings.cache_clear()
    return MarketDataService(get_settings())


# ── US gainers ─────────────────────────────────────────────────────────────────

class TestUSGainers:
    def _make_screener_row(self, **kwargs) -> dict:
        defaults = {
            "symbol": "NVDA",
            "shortName": "NVIDIA",
            "regularMarketPrice": 950.0,
            "regularMarketChangePercent": 8.5,
            "regularMarketChange": 74.5,
            "regularMarketVolume": 45_000_000,
            "averageDailyVolume3Month": 40_000_000,
            "marketCap": 2_300_000_000_000,
            "sector": "Technology",
            "industry": "Semiconductors",
        }
        return {**defaults, **kwargs}

    @patch("services.market_data.yf.Screener")
    async def test_returns_sorted_gainers(self, mock_screener_cls, service):
        import pandas as pd

        rows = [
            self._make_screener_row(symbol="NVDA", regularMarketChangePercent=8.5),
            self._make_screener_row(symbol="AMD", regularMarketChangePercent=12.0),
            self._make_screener_row(symbol="INTC", regularMarketChangePercent=3.1),
        ]
        mock_screener_cls.return_value.df = pd.DataFrame(rows)

        gainers = await service.get_us_gainers()

        assert len(gainers) == 3
        assert gainers[0].ticker == "AMD"  # Highest gainer first
        assert gainers[0].change_pct == 12.0
        assert gainers[1].ticker == "NVDA"

    @patch("services.market_data.yf.Screener")
    async def test_filters_out_non_gainers(self, mock_screener_cls, service):
        import pandas as pd

        rows = [
            self._make_screener_row(symbol="UP", regularMarketChangePercent=5.0),
            self._make_screener_row(symbol="DOWN", regularMarketChangePercent=-3.0),
            self._make_screener_row(symbol="FLAT", regularMarketChangePercent=0.0),
        ]
        mock_screener_cls.return_value.df = pd.DataFrame(rows)

        gainers = await service.get_us_gainers()

        assert len(gainers) == 1
        assert gainers[0].ticker == "UP"

    @patch("services.market_data.yf.Screener")
    async def test_empty_screener_returns_empty(self, mock_screener_cls, service):
        import pandas as pd

        mock_screener_cls.return_value.df = pd.DataFrame()

        gainers = await service.get_us_gainers()

        assert gainers == []

    @patch("services.market_data.yf.Screener")
    async def test_respects_top_n_limit(self, mock_screener_cls, service):
        import pandas as pd

        rows = [
            self._make_screener_row(
                symbol=f"S{i}", regularMarketChangePercent=float(30 - i)
            )
            for i in range(30)
        ]
        mock_screener_cls.return_value.df = pd.DataFrame(rows)

        gainers = await service.get_us_gainers()

        assert len(gainers) <= service._top_n

    @patch("services.market_data.yf.Screener")
    async def test_screener_exception_raises_market_data_error(
        self, mock_screener_cls, service
    ):
        from core.exceptions import MarketDataError

        mock_screener_cls.side_effect = RuntimeError("API down")

        with pytest.raises(MarketDataError):
            await service.get_us_gainers()


# ── Fundamentals ───────────────────────────────────────────────────────────────

class TestFundamentals:
    @patch("services.market_data.yf.Ticker")
    async def test_returns_fundamentals(self, mock_ticker_cls, service):
        mock_info = {
            "trailingPE": 45.2,
            "forwardPE": 30.1,
            "returnOnEquity": 0.32,
            "debtToEquity": 0.45,
            "revenueGrowth": 0.18,
            "earningsGrowth": 0.42,
            "profitMargins": 0.55,
            "fiftyTwoWeekHigh": 1000.0,
            "fiftyTwoWeekLow": 400.0,
            "targetMeanPrice": 1100.0,
            "recommendationKey": "buy",
        }
        mock_ticker_cls.return_value.info = mock_info

        result = await service.get_fundamentals("NVDA", "us")

        assert result.pe_ratio == 45.2
        assert result.roe == 0.32
        assert result.analyst_recommendation == "buy"

    @patch("services.market_data.yf.Ticker")
    async def test_handles_missing_fields_gracefully(self, mock_ticker_cls, service):
        mock_ticker_cls.return_value.info = {"shortName": "Test Co"}

        result = await service.get_fundamentals("TEST", "us")

        assert result.pe_ratio is None
        assert result.roe is None

    @patch("services.market_data.yf.Ticker")
    async def test_india_ticker_gets_ns_suffix(self, mock_ticker_cls, service):
        mock_ticker_cls.return_value.info = {}
        await service.get_fundamentals("RELIANCE", "india")
        mock_ticker_cls.assert_called_once_with("RELIANCE.NS")


# ── Utility functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_safe_float_with_valid_value(self):
        assert _safe_float(3.14) == 3.14

    def test_safe_float_with_none(self):
        assert _safe_float(None) is None

    def test_safe_float_with_invalid(self):
        assert _safe_float("not_a_number") is None

    def test_safe_int_with_valid_value(self):
        assert _safe_int(42) == 42

    def test_safe_int_with_none(self):
        assert _safe_int(None) is None
