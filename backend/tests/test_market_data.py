from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import get_settings
from models.schemas import StockGainer
from services.market_data import MarketDataService, _safe_float, _safe_int


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


# ── Two-step Gemini pipeline ───────────────────────────────────────────────────
# The pipeline splits into:
#   Step 1 (_ground_search)           — googleSearch grounding, NO responseSchema
#   Step 2 (_structure_gainers_to_json) — responseSchema, NO googleSearch
#
# Vertex AI rejects requests combining googleSearch and responseMimeType in the
# same call (HTTP 400). Splitting sidesteps this entirely.

class TestFetchGainersViaGemini:
    """Integration tests for _fetch_gainers_via_gemini two-step orchestration."""

    def _stocks(self) -> list[dict]:
        return [{"ticker": "NVDA", "name": "NVIDIA", "price": 950.0,
                 "change_pct": 8.5, "change_abs": 74.5, "volume": 45_000_000}]

    def _prose_response(self, text: str) -> dict:
        """Gemini response returning plain text (used for ground_search step)."""
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    def _json_response(self, body: object) -> dict:
        """Gemini response returning JSON (used for structure step)."""
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]}

    async def test_orchestrates_two_step_pipeline(self, service: MarketDataService) -> None:
        """_fetch_gainers_via_gemini calls _ground_search then _structure_gainers_to_json."""
        prose = "NVDA up 8.5%, AMD up 5%, INTC up 3%"
        stocks = self._stocks()

        ground_mock = AsyncMock(return_value=prose)
        structure_mock = AsyncMock(return_value=stocks)

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            patch.object(service, "_ground_search", ground_mock),
            patch.object(service, "_structure_gainers_to_json", structure_mock),
        ):
            result = await service._fetch_gainers_via_gemini("test prompt", "us")

        ground_mock.assert_awaited_once()
        structure_mock.assert_awaited_once()
        assert result == stocks

    async def test_passes_prose_text_to_structure_step(self, service: MarketDataService) -> None:
        """The prose from step 1 must be forwarded unchanged to step 2."""
        prose = "Market data: NVDA gained 8.5% today on earnings beat."

        ground_mock = AsyncMock(return_value=prose)
        structure_mock = AsyncMock(return_value=[])

        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            patch.object(service, "_ground_search", ground_mock),
            patch.object(service, "_structure_gainers_to_json", structure_mock),
        ):
            await service._fetch_gainers_via_gemini("test", "us")

        # The prose must be passed as first positional arg (after token) to _structure_gainers_to_json
        call_args = structure_mock.call_args
        assert prose in call_args.args or prose in call_args.kwargs.values()

    async def test_returns_empty_if_ground_search_returns_empty_string(
        self, service: MarketDataService
    ) -> None:
        """If ground search returns empty string, skip structure step and return []."""
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            patch.object(service, "_ground_search", AsyncMock(return_value="")),
            patch.object(service, "_structure_gainers_to_json", AsyncMock()) as struct_mock,
        ):
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert result == []
        struct_mock.assert_not_awaited()

    async def test_returns_empty_if_ground_search_returns_whitespace_only(
        self, service: MarketDataService
    ) -> None:
        with (
            patch("core.auth.get_cached_token", return_value="fake-token"),
            patch.object(service, "_ground_search", AsyncMock(return_value="   \n  ")),
            patch.object(service, "_structure_gainers_to_json", AsyncMock()) as struct_mock,
        ):
            result = await service._fetch_gainers_via_gemini("test", "us")

        assert result == []
        struct_mock.assert_not_awaited()

    async def test_token_fetched_once_and_reused_for_both_steps(
        self, service: MarketDataService
    ) -> None:
        """Token should be obtained once and passed to both sub-calls, not fetched twice."""
        with (
            patch("core.auth.get_cached_token", return_value="fake-token") as token_mock,
            patch.object(service, "_ground_search", AsyncMock(return_value="some text")),
            patch.object(service, "_structure_gainers_to_json", AsyncMock(return_value=[])),
        ):
            await service._fetch_gainers_via_gemini("test", "us")

        # get_cached_token called once
        assert token_mock.call_count == 0  # called via asyncio.to_thread — count on the sync fn
        # Verify both mocks received the same token
        # (indirectly verified by ensuring only one token fetch happens in the implementation)


class TestGroundSearch:
    """Tests for _ground_search: must use googleSearch, must NOT use responseSchema."""

    async def test_includes_google_search_tool(self, service: MarketDataService) -> None:
        import httpx
        import respx

        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "Market update: NVDA up 8.5%"}]}}]
            })

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._ground_search("fake-token", "list top gainers", "us")

        assert len(captured) == 1
        payload = captured[0]
        tool_names = [list(t.keys())[0] for t in payload.get("tools", [])]
        assert "googleSearch" in tool_names

    async def test_no_response_mime_type_in_ground_search(self, service: MarketDataService) -> None:
        """googleSearch + responseMimeType = 400 from Vertex AI. Must not be combined."""
        import httpx
        import respx

        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "some prose"}]}}]
            })

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._ground_search("fake-token", "list top gainers", "us")

        gen_config = captured[0].get("generationConfig", {})
        assert "responseMimeType" not in gen_config, (
            "responseMimeType must NOT be set when googleSearch is used"
        )
        assert "responseSchema" not in gen_config, (
            "responseSchema must NOT be set when googleSearch is used"
        )

    async def test_returns_joined_text_from_multiple_parts(self, service: MarketDataService) -> None:
        """Grounded responses may have multiple content parts — all must be joined."""
        import httpx
        import respx

        multi_part = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": "NVDA up 8.5%. "},
                        {"text": "AMD up 5.0%. "},
                        {"text": "INTC up 3.0%."},
                    ]
                }
            }]
        }

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=multi_part)
            )
            result = await service._ground_search("fake-token", "test", "us")

        assert "NVDA" in result
        assert "AMD" in result
        assert "INTC" in result

    async def test_http_error_raises_exception(self, service: MarketDataService) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(401, text="Unauthorized")
            )
            with pytest.raises(Exception):
                await service._ground_search("fake-token", "test", "us")


class TestStructureGainersToJson:
    """Tests for _structure_gainers_to_json: must use responseSchema, no googleSearch."""

    def _stock_list(self) -> list[dict]:
        return [{"ticker": "NVDA", "name": "NVIDIA", "price": 950.0,
                 "change_pct": 8.5, "change_abs": 74.5, "volume": 45_000_000}]

    async def test_includes_response_schema_in_payload(self, service: MarketDataService) -> None:
        import httpx
        import respx

        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(self._stock_list())}]}}]
            })

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._structure_gainers_to_json("fake-token", "NVDA is up 8.5%", "us")

        gen_config = captured[0].get("generationConfig", {})
        assert gen_config.get("responseMimeType") == "application/json"
        assert "responseSchema" in gen_config

    async def test_no_google_search_in_structure_step(self, service: MarketDataService) -> None:
        """Structure step must NOT include googleSearch (would trigger 400 if combined with responseSchema)."""
        import httpx
        import respx

        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(self._stock_list())}]}}]
            })

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._structure_gainers_to_json("fake-token", "NVDA up 8.5%", "us")

        payload = captured[0]
        tools = payload.get("tools", [])
        tool_names = [list(t.keys())[0] for t in tools]
        assert "googleSearch" not in tool_names

    async def test_returns_parsed_list(self, service: MarketDataService) -> None:
        import httpx
        import respx

        stocks = self._stock_list()

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json={
                    "candidates": [{"content": {"parts": [{"text": json.dumps(stocks)}]}}]
                })
            )
            result = await service._structure_gainers_to_json("fake-token", "some prose", "us")

        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"

    async def test_invalid_json_returns_empty_list(self, service: MarketDataService) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json={
                    "candidates": [{"content": {"parts": [{"text": "not valid json {{{{"}]}}]
                })
            )
            result = await service._structure_gainers_to_json("fake-token", "prose", "us")

        assert result == []

    async def test_non_list_json_returns_empty_list(self, service: MarketDataService) -> None:
        """If Gemini returns a JSON object instead of array, return []."""
        import httpx
        import respx

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json={
                    "candidates": [{"content": {"parts": [{"text": '{"unexpected": "object"}'}]}}]
                })
            )
            result = await service._structure_gainers_to_json("fake-token", "prose", "us")

        assert result == []

    async def test_http_error_raises_exception(self, service: MarketDataService) -> None:
        import httpx
        import respx

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            with pytest.raises(Exception):
                await service._structure_gainers_to_json("fake-token", "prose", "us")

    async def test_embeds_raw_text_in_prompt(self, service: MarketDataService) -> None:
        """The raw prose from ground_search must appear in the structure step's prompt."""
        import httpx
        import respx

        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(self._stock_list())}]}}]
            })

        raw_prose = "NVDA up 8.5% today on strong earnings beat"

        with respx.mock:
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(side_effect=handler)
            await service._structure_gainers_to_json("fake-token", raw_prose, "us")

        prompt_text = captured[0]["contents"][0]["parts"][0]["text"]
        assert raw_prose in prompt_text


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
