from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import get_settings
from models.schemas import StockGainer
from services.market_data import MarketDataService, _extract_json_list, _safe_float, _safe_int


@pytest.fixture
def service() -> MarketDataService:
    get_settings.cache_clear()
    return MarketDataService(get_settings())


# ── _build_gainers ─────────────────────────────────────────────────────────────
# This method transforms raw Gemini JSON dicts into StockGainer objects,
# filters non-gainers, sorts by change_pct, and applies quality scores.

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
        rows = [
            self._row(ticker=""),      # Empty — skip
            self._row(ticker="NVDA"),  # Valid
        ]
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
            # no "sector"
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
            {"ticker": "BAD", "price": "not_a_number"},  # Malformed
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


# ── Gemini-based gainers ───────────────────────────────────────────────────────
# Tests for get_us_gainers / get_india_gainers, mocking _fetch_gainers_via_gemini
# to avoid real GCP calls.

class TestGeminiGainers:
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
        with patch.object(service, "_fetch_gainers_via_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_us_gainers()

        assert result[0].ticker == "AMD"
        assert result[0].change_pct == 12.0
        assert result[-1].change_pct < result[0].change_pct

    async def test_get_us_gainers_respects_top_n_limit(self, service: MarketDataService) -> None:
        service._top_n = 3
        raw = [self._raw_row(ticker=f"S{i}", change_pct=float(20 - i)) for i in range(10)]
        with patch.object(service, "_fetch_gainers_via_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_us_gainers()
        assert len(result) <= 3

    async def test_get_us_gainers_with_quality_scores(self, service: MarketDataService) -> None:
        raw = [self._raw_row()]
        with patch.object(service, "_fetch_gainers_via_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_us_gainers()
        assert result[0].quality_score is not None
        assert result[0].quality_label is not None

    async def test_get_us_gainers_wraps_errors_as_market_data_error(
        self, service: MarketDataService
    ) -> None:
        from core.exceptions import MarketDataError

        with patch.object(
            service, "_fetch_gainers_via_gemini", new=AsyncMock(side_effect=RuntimeError("API down"))
        ):
            with pytest.raises(MarketDataError, match="Failed to fetch US gainers"):
                await service.get_us_gainers()

    async def test_get_india_gainers_returns_india_market_tag(
        self, service: MarketDataService
    ) -> None:
        raw = [self._raw_row(ticker="RELIANCE", change_pct=5.2)]
        with patch.object(service, "_fetch_gainers_via_gemini", new=AsyncMock(return_value=raw)):
            result = await service.get_india_gainers()
        assert result[0].market == "india"

    async def test_get_india_gainers_wraps_errors_as_market_data_error(
        self, service: MarketDataService
    ) -> None:
        from core.exceptions import MarketDataError

        with patch.object(
            service, "_fetch_gainers_via_gemini", new=AsyncMock(side_effect=RuntimeError("Timeout"))
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


# ── _fetch_gainers_via_gemini (REST layer) ────────────────────────────────────

class TestFetchGainersViaGemini:
    """Tests for the Vertex AI REST call layer using respx to mock httpx."""

    def _gemini_response(self, body: object) -> dict:
        return {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps(body)}]
                }
            }]
        }

    async def test_parses_direct_array_response(self, service: MarketDataService) -> None:
        import httpx
        import respx

        stocks = [
            {"ticker": "NVDA", "name": "NVIDIA", "price": 950.0,
             "change_pct": 8.5, "change_abs": 74.5, "volume": 45_000_000}
        ]
        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response(stocks))
            )
            result = await service._fetch_gainers_via_gemini("test prompt", "us")

        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"

    async def test_unwraps_dict_with_gainers_key(self, service: MarketDataService) -> None:
        """Gemini sometimes wraps the array in a dict like {"gainers": [...]}."""
        import httpx
        import respx

        stocks = [{"ticker": "AMD", "name": "AMD", "price": 100.0,
                   "change_pct": 5.0, "change_abs": 5.0, "volume": 1_000_000}]
        wrapped = {"gainers": stocks}

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response(wrapped))
            )
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert len(result) == 1
        assert result[0]["ticker"] == "AMD"

    async def test_unwraps_dict_with_items_key(self, service: MarketDataService) -> None:
        import httpx
        import respx

        stocks = [{"ticker": "INTC", "name": "Intel", "price": 30.0,
                   "change_pct": 4.0, "change_abs": 1.2, "volume": 2_000_000}]
        wrapped = {"items": stocks}

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response(wrapped))
            )
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert result[0]["ticker"] == "INTC"

    async def test_returns_empty_list_for_invalid_json(self, service: MarketDataService) -> None:
        import httpx
        import respx

        bad_response = {
            "candidates": [{"content": {"parts": [{"text": "not json at all!!!"}]}}]
        }

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=bad_response)
            )
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert result == []

    async def test_http_error_raises_exception(self, service: MarketDataService) -> None:
        import httpx
        import respx

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )
            with pytest.raises(Exception):
                await service._fetch_gainers_via_gemini("test", "us")

    async def test_includes_google_search_tool_in_payload(
        self, service: MarketDataService
    ) -> None:
        """Verify the request payload includes googleSearch but NOT responseMimeType."""
        import httpx
        import respx

        captured_request: list[httpx.Request] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_request.append(request)
            stocks = [{"ticker": "TEST", "name": "Test", "price": 10.0,
                       "change_pct": 5.0, "change_abs": 0.5, "volume": 100_000}]
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(stocks)}]}}]
            })

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=capture)
            await service._fetch_gainers_via_gemini("test prompt", "us")

        assert len(captured_request) == 1
        payload = json.loads(captured_request[0].content)

        # Must include Google Search grounding tool
        assert "tools" in payload
        tool_names = [list(t.keys())[0] for t in payload["tools"]]
        assert "googleSearch" in tool_names

        # MUST NOT include responseMimeType or responseSchema —
        # these are incompatible with googleSearch grounding (causes 400 from Vertex AI)
        gen_config = payload.get("generationConfig", {})
        assert "responseMimeType" not in gen_config, (
            "responseMimeType must not be set when googleSearch is used"
        )
        assert "responseSchema" not in gen_config, (
            "responseSchema must not be set when googleSearch is used"
        )

    async def test_joins_multiple_response_parts(self, service: MarketDataService) -> None:
        """Grounded responses can have multiple content parts — all must be joined."""
        import httpx
        import respx

        stocks = [{"ticker": "NVDA", "name": "NVIDIA", "price": 950.0,
                   "change_pct": 8.5, "change_abs": 74.5, "volume": 45_000_000}]
        # Split the JSON across two parts (simulating grounding citation insertion)
        full_text = json.dumps(stocks)
        half = len(full_text) // 2
        multi_part_response = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": full_text[:half]},
                        {"text": full_text[half:]},
                    ]
                }
            }]
        }

        with (
            patch.object(MarketDataService, "_get_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=multi_part_response)
            )
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"


# ── _extract_json_list ────────────────────────────────────────────────────────
# Tests for the robust JSON extractor used when googleSearch grounding is active.
# The model may return prose, markdown fences, or dict wrappers around the array.

class TestExtractJsonList:
    def _stock(self, ticker: str = "NVDA") -> dict:
        return {"ticker": ticker, "name": "Test", "price": 100.0,
                "change_pct": 5.0, "change_abs": 5.0, "volume": 1_000_000}

    def test_direct_json_array(self) -> None:
        raw = json.dumps([self._stock()])
        assert _extract_json_list(raw)[0]["ticker"] == "NVDA"

    def test_json_array_in_prose(self) -> None:
        stocks = [self._stock()]
        text = f"Here are today's gainers:\n{json.dumps(stocks)}\nNote: data from Google Search."
        result = _extract_json_list(text)
        assert len(result) == 1

    def test_json_wrapped_in_markdown_fence(self) -> None:
        stocks = [self._stock()]
        text = f"```json\n{json.dumps(stocks)}\n```"
        result = _extract_json_list(text)
        assert len(result) == 1

    def test_json_wrapped_in_bare_markdown_fence(self) -> None:
        stocks = [self._stock()]
        text = f"```\n{json.dumps(stocks)}\n```"
        result = _extract_json_list(text)
        assert len(result) == 1

    def test_dict_wrapper_gainers_key(self) -> None:
        wrapped = {"gainers": [self._stock()]}
        assert _extract_json_list(json.dumps(wrapped))[0]["ticker"] == "NVDA"

    def test_dict_wrapper_stocks_key(self) -> None:
        wrapped = {"stocks": [self._stock("AMD")]}
        assert _extract_json_list(json.dumps(wrapped))[0]["ticker"] == "AMD"

    def test_dict_wrapper_items_key(self) -> None:
        wrapped = {"items": [self._stock("INTC")]}
        assert _extract_json_list(json.dumps(wrapped))[0]["ticker"] == "INTC"

    def test_invalid_text_returns_empty_list(self) -> None:
        assert _extract_json_list("no json here at all") == []

    def test_empty_string_returns_empty_list(self) -> None:
        assert _extract_json_list("") == []

    def test_multiple_stocks_all_returned(self) -> None:
        stocks = [self._stock("NVDA"), self._stock("AMD"), self._stock("INTC")]
        result = _extract_json_list(json.dumps(stocks))
        assert len(result) == 3

    def test_dict_without_known_key_returns_empty(self) -> None:
        # Dict with unknown key — nothing to extract
        assert _extract_json_list(json.dumps({"unknown_key": [self._stock()]})) == []


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
        mock_ticker_cls.return_value.info = {"shortName": "Test Co"}  # All numeric fields missing
        result = await service.get_fundamentals("TEST", "us")
        assert result.pe_ratio is None
        assert result.roe is None
        assert result.profit_margin is None

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
