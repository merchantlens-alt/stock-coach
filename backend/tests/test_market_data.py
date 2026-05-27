from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.config import get_settings
from models.schemas import StockGainer
from services.market_data import (
    MarketDataService,
    resolve_ticker_by_name,
    _parse_pipe_table,
    _safe_float,
    _safe_int,
)


@pytest.fixture
def service() -> MarketDataService:
    get_settings.cache_clear()
    return MarketDataService(get_settings())


# ── _build_gainers ─────────────────────────────────────────────────────────────

class TestBuildGainers:
    def _row(self, **kwargs) -> dict:
        defaults = {
            "ticker": "NVDA",
            "name": "NVIDIA Corporation",
            "price": 950.0,
            "change_pct": 8.5,
            "change_abs": 74.5,
            "volume": 45_000_000,
            "sector": "Technology",
        }
        return {**defaults, **kwargs}

    def test_builds_stock_gainer_from_valid_raw_dict(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row()], "us")
        assert len(result) == 1
        g = result[0]
        assert g.ticker == "NVDA"
        assert g.price == 950.0
        assert g.market == "us"
        assert g.change_pct == 8.5
        assert g.volume == 45_000_000

    def test_filters_out_non_positive_change_pct(self, service: MarketDataService) -> None:
        rows = [
            self._row(ticker="UP", change_pct=5.0),
            self._row(ticker="DOWN", change_pct=-3.0),
            self._row(ticker="FLAT", change_pct=0.0),
        ]
        result = service._build_gainers(rows, "us")
        assert len(result) == 1
        assert result[0].ticker == "UP"

    def test_sorts_by_change_pct_descending(self, service: MarketDataService) -> None:
        rows = [
            self._row(ticker="LOW", change_pct=3.0),
            self._row(ticker="HIGH", change_pct=12.0),
            self._row(ticker="MID", change_pct=7.0),
        ]
        result = service._build_gainers(rows, "us")
        assert result[0].ticker == "HIGH"
        assert result[1].ticker == "MID"
        assert result[2].ticker == "LOW"

    def test_applies_quality_score_to_each_gainer(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row()], "us")
        assert result[0].quality_score is not None
        assert result[0].quality_label is not None
        assert 0 <= result[0].quality_score <= 10

    def test_quality_label_is_valid_value(self, service: MarketDataService) -> None:
        valid = {"Strong", "Moderate", "Watch", "Risky"}
        result = service._build_gainers([self._row()], "us")
        assert result[0].quality_label in valid

    def test_skips_rows_with_empty_ticker(self, service: MarketDataService) -> None:
        rows = [self._row(ticker=""), self._row(ticker="NVDA")]
        result = service._build_gainers(rows, "us")
        assert len(result) == 1
        assert result[0].ticker == "NVDA"

    def test_handles_missing_optional_sector_field(self, service: MarketDataService) -> None:
        row = {
            "ticker": "TEST",
            "name": "Test Co",
            "price": 20.0,
            "change_pct": 5.0,
            "change_abs": 1.0,
            "volume": 500_000,
        }
        result = service._build_gainers([row], "us")
        assert len(result) == 1
        assert result[0].sector is None

    def test_rounds_change_pct_to_2_decimal_places(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row(change_pct=8.5678)], "us")
        assert result[0].change_pct == 8.57

    def test_empty_raw_list_returns_empty(self, service: MarketDataService) -> None:
        assert service._build_gainers([], "us") == []

    def test_tolerates_malformed_row_and_continues(self, service: MarketDataService) -> None:
        rows = [
            self._row(ticker="GOOD"),
            {"ticker": "BAD", "price": "not_a_number"},
        ]
        result = service._build_gainers(rows, "us")
        tickers = [g.ticker for g in result]
        assert "GOOD" in tickers
        assert "BAD" not in tickers

    def test_india_market_tag_applied_to_all_gainers(self, service: MarketDataService) -> None:
        result = service._build_gainers(
            [self._row(ticker="RELIANCE"), self._row(ticker="TCS", change_pct=4.0)],
            "india",
        )
        assert all(g.market == "india" for g in result)

    def test_ticker_uppercased_automatically(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row(ticker="nvda")], "us")
        assert result[0].ticker == "NVDA"

    def test_multiple_gainers_all_have_quality_scores(self, service: MarketDataService) -> None:
        rows = [self._row(ticker=f"S{i}", change_pct=float(10 - i)) for i in range(5)]
        result = service._build_gainers(rows, "us")
        assert all(g.quality_score is not None for g in result)
        assert all(g.quality_label is not None for g in result)


# ── _parse_pipe_table ─────────────────────────────────────────────────────────
# Gemini outputs a pipe-delimited table (not JSON) when googleSearch grounding
# is active — JSON mode is incompatible with grounding on Vertex AI.
# This function parses that table deterministically in pure Python.

class TestParsePipeTable:
    def _line(self, ticker="NVDA", name="NVIDIA", price=950.0,
               pct=8.5, abs_=74.5, vol=45_000_000, sector="Technology"):
        return f"{ticker}|{name}|{price}|{pct}|{abs_}|{vol}|{sector}"

    def test_parses_single_valid_line(self) -> None:
        result = _parse_pipe_table(self._line())
        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"
        assert result[0]["price"] == 950.0
        assert result[0]["change_pct"] == 8.5
        assert result[0]["volume"] == 45_000_000

    def test_parses_multiple_lines(self) -> None:
        text = "\n".join([
            self._line("NVDA", pct=8.5),
            self._line("AMD", pct=5.2),
            self._line("INTC", pct=3.1),
        ])
        assert len(_parse_pipe_table(text)) == 3

    def test_skips_blank_lines(self) -> None:
        text = self._line() + "\n\n\n" + self._line("AMD", pct=5.2)
        assert len(_parse_pipe_table(text)) == 2

    def test_skips_header_row_with_non_numeric_price(self) -> None:
        text = "TICKER|NAME|PRICE|CHANGE_PCT|CHANGE_ABS|VOLUME|SECTOR\n" + self._line()
        assert len(_parse_pipe_table(text)) == 1

    def test_skips_markdown_separator_lines(self) -> None:
        text = "---|---|---|---|---|---|---\n" + self._line()
        assert len(_parse_pipe_table(text)) == 1

    def test_handles_missing_sector_column(self) -> None:
        text = "NVDA|NVIDIA|950.0|8.5|74.5|45000000"
        result = _parse_pipe_table(text)
        assert len(result) == 1
        assert result[0]["sector"] is None

    def test_handles_price_with_dollar_sign(self) -> None:
        text = "NVDA|NVIDIA|$950.00|8.5|$74.50|45000000|Technology"
        result = _parse_pipe_table(text)
        assert result[0]["price"] == 950.0

    def test_handles_price_with_rupee_sign(self) -> None:
        text = "RELIANCE|Reliance|₹2850.00|5.2|₹141.0|8000000|Energy"
        result = _parse_pipe_table(text)
        assert result[0]["price"] == 2850.0

    def test_handles_commas_in_numbers(self) -> None:
        text = "NVDA|NVIDIA|950.00|8.5|74.50|45,000,000|Technology"
        result = _parse_pipe_table(text)
        assert result[0]["volume"] == 45_000_000

    def test_handles_pct_with_plus_sign(self) -> None:
        text = "NVDA|NVIDIA|950.00|+8.5|74.50|45000000|Technology"
        result = _parse_pipe_table(text)
        assert result[0]["change_pct"] == 8.5

    def test_skips_lines_with_fewer_than_6_fields(self) -> None:
        text = "NVDA|NVIDIA|950.0|8.5|74.5"  # only 5 fields
        assert _parse_pipe_table(text) == []

    def test_skips_non_alpha_tickers(self) -> None:
        text = "123|Bad Ticker|10.0|5.0|0.5|100000|Tech"
        assert _parse_pipe_table(text) == []

    def test_returns_empty_for_empty_string(self) -> None:
        assert _parse_pipe_table("") == []

    def test_ticker_uppercased(self) -> None:
        text = "nvda|NVIDIA|950.0|8.5|74.5|45000000|Technology"
        result = _parse_pipe_table(text)
        assert result[0]["ticker"] == "NVDA"


# ── _fetch_gainers_gemini (Gemini REST layer) ─────────────────────────────────

class TestFetchGainersGemini:
    """Tests for _fetch_gainers_gemini — mocks Vertex AI HTTP calls via respx."""

    def _gemini_response(self, text: str) -> dict:
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    def _table_text(self, stocks: list[tuple]) -> str:
        return "\n".join(
            f"{t}|{n}|{p}|{pct}|{abs_}|{vol}|Technology"
            for t, n, p, pct, abs_, vol in stocks
        )

    async def test_parses_pipe_table_from_gemini(self, service: MarketDataService) -> None:
        import httpx, respx
        table = self._table_text([("NVDA", "NVIDIA", 950.0, 8.5, 74.5, 45_000_000)])

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response(table))
            )
            result = await service._fetch_gainers_gemini("prompt", "us")

        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"

    async def test_returns_multiple_stocks(self, service: MarketDataService) -> None:
        import httpx, respx
        table = self._table_text([
            ("NVDA", "NVIDIA", 950.0, 8.5, 74.5, 45_000_000),
            ("AMD", "AMD Inc", 100.0, 5.2, 5.0, 10_000_000),
            ("INTC", "Intel", 30.0, 3.1, 0.9, 5_000_000),
        ])

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response(table))
            )
            result = await service._fetch_gainers_gemini("prompt", "us")

        assert len(result) == 3

    async def test_payload_includes_google_search_tool(self, service: MarketDataService) -> None:
        import httpx, respx, json
        captured: list[dict] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return httpx.Response(200, json=self._gemini_response(
                "NVDA|NVIDIA|950.0|8.5|74.5|45000000|Technology"
            ))

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._fetch_gainers_gemini("prompt", "us")

        payload = captured[0]
        tool_names = [list(t.keys())[0] for t in payload.get("tools", [])]
        assert "googleSearch" in tool_names
        gen_config = payload.get("generationConfig", {})
        assert "responseMimeType" not in gen_config
        assert "responseSchema" not in gen_config

    async def test_http_error_raises(self, service: MarketDataService) -> None:
        import httpx, respx

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )
            with pytest.raises(Exception):
                await service._fetch_gainers_gemini("prompt", "us")

    async def test_empty_gemini_response_returns_empty_list(
        self, service: MarketDataService
    ) -> None:
        import httpx, respx

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response("No data available."))
            )
            result = await service._fetch_gainers_gemini("prompt", "us")

        assert result == []


# ── get_us_gainers / get_india_gainers ────────────────────────────────────────

class TestGetGainers:
    def _raw_row(self, **kwargs) -> dict:
        defaults = {
            "ticker": "NVDA",
            "name": "NVIDIA",
            "price": 950.0,
            "change_pct": 8.5,
            "change_abs": 74.5,
            "volume": 45_000_000,
            "sector": "Technology",
        }
        return {**defaults, **kwargs}

    async def test_get_us_gainers_returns_sorted_list(self, service: MarketDataService) -> None:
        raw = [
            self._raw_row(ticker="AMD", change_pct=12.0),
            self._raw_row(ticker="NVDA", change_pct=8.5),
            self._raw_row(ticker="INTC", change_pct=3.0),
        ]
        with patch.object(service, "_fetch_gainers_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_us_gainers()

        assert result[0].ticker == "AMD"
        assert result[-1].change_pct < result[0].change_pct

    async def test_get_us_gainers_respects_top_n_limit(self, service: MarketDataService) -> None:
        service._top_n = 3
        raw = [self._raw_row(ticker=f"S{i}", change_pct=float(20 - i)) for i in range(10)]
        with patch.object(service, "_fetch_gainers_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_us_gainers()
        assert len(result) <= 3

    async def test_get_us_gainers_wraps_errors_as_market_data_error(
        self, service: MarketDataService
    ) -> None:
        from core.exceptions import MarketDataError

        with patch.object(
            service, "_fetch_gainers_gemini", new=AsyncMock(side_effect=RuntimeError("API down"))
        ):
            with pytest.raises(MarketDataError, match="Failed to fetch US gainers"):
                await service.get_us_gainers()

    async def test_get_india_gainers_returns_india_market_tag(
        self, service: MarketDataService
    ) -> None:
        raw = [self._raw_row(ticker="RELIANCE", change_pct=5.2)]
        with patch.object(service, "_fetch_gainers_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_india_gainers()
        assert result[0].market == "india"

    async def test_get_india_gainers_wraps_errors_as_market_data_error(
        self, service: MarketDataService
    ) -> None:
        from core.exceptions import MarketDataError

        with patch.object(
            service, "_fetch_gainers_gemini", new=AsyncMock(side_effect=RuntimeError("Timeout"))
        ):
            with pytest.raises(MarketDataError, match="Failed to fetch India gainers"):
                await service.get_india_gainers()

    async def test_get_gainers_delegates_to_correct_market(
        self, service: MarketDataService
    ) -> None:
        raw = [self._raw_row()]
        us_mock = AsyncMock(return_value=raw)
        india_mock = AsyncMock(return_value=raw)

        with (
            patch.object(service, "get_us_gainers", us_mock),
            patch.object(service, "get_india_gainers", india_mock),
        ):
            await service.get_gainers("us")
            await service.get_gainers("india")

        us_mock.assert_called_once()
        india_mock.assert_called_once()


# ── resolve_ticker_by_name ─────────────────────────────────────────────────────

class TestResolveTickerByName:
    """Tests for the company name → ticker resolution helper."""

    def _search_response(self, quotes: list[dict]) -> dict:
        return {"quotes": quotes}

    def _equity(self, symbol: str, exchange: str = "NMS", quote_type: str = "EQUITY") -> dict:
        return {"symbol": symbol, "exchange": exchange, "quoteType": quote_type}

    async def test_resolves_company_name_to_us_ticker(self) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.get(url__regex=r".*finance\.yahoo\.com.*search.*").mock(
                return_value=httpx.Response(
                    200,
                    json=self._search_response([self._equity("NVDA", "NMS")])
                )
            )
            result = await resolve_ticker_by_name("NVIDIA", "us")

        assert result == "NVDA"

    async def test_resolves_company_name_to_india_ticker(self) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.get(url__regex=r".*finance\.yahoo\.com.*search.*").mock(
                return_value=httpx.Response(
                    200,
                    json=self._search_response([self._equity("RELIANCE.NS", "NSE")])
                )
            )
            result = await resolve_ticker_by_name("Reliance", "india")

        assert result == "RELIANCE"

    async def test_skips_non_equity_results(self) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.get(url__regex=r".*finance\.yahoo\.com.*search.*").mock(
                return_value=httpx.Response(
                    200,
                    json=self._search_response([
                        self._equity("NVDA-WT", "NMS", quote_type="WARRANT"),
                        self._equity("NVDA", "NMS", quote_type="EQUITY"),
                    ])
                )
            )
            result = await resolve_ticker_by_name("NVIDIA", "us")

        assert result == "NVDA"

    async def test_returns_none_when_no_match(self) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.get(url__regex=r".*finance\.yahoo\.com.*search.*").mock(
                return_value=httpx.Response(200, json=self._search_response([]))
            )
            result = await resolve_ticker_by_name("XYZNOTREAL", "us")

        assert result is None

    async def test_returns_none_on_http_error(self) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.get(url__regex=r".*finance\.yahoo\.com.*search.*").mock(
                return_value=httpx.Response(500, text="Server error")
            )
            result = await resolve_ticker_by_name("NVIDIA", "us")

        assert result is None


# ── Fundamentals (yfinance) ────────────────────────────────────────────────────

class TestFundamentals:
    @patch("services.market_data.yf.Ticker")
    async def test_returns_fundamentals_data(self, mock_ticker_cls, service: MarketDataService) -> None:
        mock_ticker_cls.return_value.info = {
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
        result = await service.get_fundamentals("NVDA", "us")
        assert result.pe_ratio == 45.2
        assert result.roe == 0.32
        assert result.analyst_recommendation == "buy"

    @patch("services.market_data.yf.Ticker")
    async def test_handles_missing_fields_gracefully(self, mock_ticker_cls, service: MarketDataService) -> None:
        mock_ticker_cls.return_value.info = {"shortName": "Test Co"}
        result = await service.get_fundamentals("TEST", "us")
        assert result.pe_ratio is None
        assert result.roe is None

    @patch("services.market_data.yf.Ticker")
    async def test_india_ticker_appends_ns_suffix(self, mock_ticker_cls, service: MarketDataService) -> None:
        mock_ticker_cls.return_value.info = {"shortName": "Reliance"}
        await service.get_fundamentals("RELIANCE", "india")
        mock_ticker_cls.assert_called_once_with("RELIANCE.NS")

    @patch("services.market_data.yf.Ticker")
    async def test_us_ticker_no_suffix_added(self, mock_ticker_cls, service: MarketDataService) -> None:
        mock_ticker_cls.return_value.info = {"shortName": "NVIDIA"}
        await service.get_fundamentals("NVDA", "us")
        mock_ticker_cls.assert_called_once_with("NVDA")

    @patch("services.market_data.yf.Ticker")
    async def test_yfinance_exception_raises_market_data_error(
        self, mock_ticker_cls, service: MarketDataService
    ) -> None:
        from core.exceptions import MarketDataError

        mock_ticker_cls.side_effect = RuntimeError("yfinance timeout")
        with pytest.raises(MarketDataError):
            await service.get_fundamentals("NVDA", "us")


# ── Utility helpers ────────────────────────────────────────────────────────────

class TestHelpers:
    def test_safe_float_with_valid_float(self) -> None:
        assert _safe_float(3.14) == 3.14

    def test_safe_float_with_integer(self) -> None:
        assert _safe_float(42) == 42.0

    def test_safe_float_with_none(self) -> None:
        assert _safe_float(None) is None

    def test_safe_float_with_non_numeric_string(self) -> None:
        assert _safe_float("not_a_number") is None

    def test_safe_float_with_numeric_string(self) -> None:
        assert _safe_float("3.14") == 3.14

    def test_safe_int_with_valid_int(self) -> None:
        assert _safe_int(42) == 42

    def test_safe_int_with_float_truncates(self) -> None:
        assert _safe_int(3.7) == 3

    def test_safe_int_with_none(self) -> None:
        assert _safe_int(None) is None

    def test_safe_int_with_non_numeric_string(self) -> None:
        assert _safe_int("not_a_number") is None
