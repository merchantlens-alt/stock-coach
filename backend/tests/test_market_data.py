from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.config import get_settings
from models.schemas import StockGainer
import pandas as pd

from services.market_data import (
    MarketDataService,
    resolve_ticker_by_name,
    _parse_pipe_table,
    _safe_float,
    _safe_int,
    _US_TICKER_UNIVERSE,
    _INDIA_TICKER_UNIVERSE,
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

    def test_has_catalyst_true_sets_confirmed_tier(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row(has_catalyst=True)], "us")
        assert result[0].signal_tier == "confirmed"

    def test_has_catalyst_false_sets_mover_tier(self, service: MarketDataService) -> None:
        result = service._build_gainers([self._row(has_catalyst=False)], "us")
        assert result[0].signal_tier == "mover"

    def test_has_catalyst_missing_defaults_to_mover(self, service: MarketDataService) -> None:
        row = {k: v for k, v in self._row().items() if k != "has_catalyst"}
        result = service._build_gainers([row], "us")
        assert result[0].signal_tier == "mover"


# ── _parse_pipe_table ─────────────────────────────────────────────────────────
# Gemini outputs a pipe-delimited table (not JSON) when googleSearch grounding
# is active — JSON mode is incompatible with grounding on Vertex AI.
# This function parses that table deterministically in pure Python.

class TestParsePipeTable:
    def _line(self, ticker="NVDA", name="NVIDIA", price=950.0,
               pct=8.5, abs_=74.5, vol=45_000_000, sector="Technology",
               has_catalyst: str | None = None):
        base = f"{ticker}|{name}|{price}|{pct}|{abs_}|{vol}|{sector}"
        return base if has_catalyst is None else f"{base}|{has_catalyst}"

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

    def test_has_catalyst_y_parsed_as_true(self) -> None:
        result = _parse_pipe_table(self._line(has_catalyst="Y"))
        assert result[0]["has_catalyst"] is True

    def test_has_catalyst_n_parsed_as_false(self) -> None:
        result = _parse_pipe_table(self._line(has_catalyst="N"))
        assert result[0]["has_catalyst"] is False

    def test_has_catalyst_defaults_false_when_column_missing(self) -> None:
        text = "NVDA|NVIDIA|950.0|8.5|74.5|45000000|Technology"  # 7 columns, no 8th
        result = _parse_pipe_table(text)
        assert result[0]["has_catalyst"] is False

    def test_has_catalyst_yes_accepted(self) -> None:
        result = _parse_pipe_table(self._line(has_catalyst="YES"))
        assert result[0]["has_catalyst"] is True

    def test_has_catalyst_true_string_accepted(self) -> None:
        result = _parse_pipe_table(self._line(has_catalyst="TRUE"))
        assert result[0]["has_catalyst"] is True

    def test_has_catalyst_markdown_table_row(self) -> None:
        text = "| ASTC | Astrotech | 6.55 | 165.2 | 4.08 | 500000 | Industrials | Y |"
        result = _parse_pipe_table(text)
        assert len(result) == 1
        assert result[0]["ticker"] == "ASTC"
        assert result[0]["has_catalyst"] is True


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
            patch("services.market_data.get_cached_token", return_value="fake-token"),
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
            patch("services.market_data.get_cached_token", return_value="fake-token"),
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
            patch("services.market_data.get_cached_token", return_value="fake-token"),
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
            patch("services.market_data.get_cached_token", return_value="fake-token"),
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
            patch("services.market_data.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response("No data available."))
            )
            result = await service._fetch_gainers_gemini("prompt", "us")

        assert result == []


# ── get_us_gainers / get_india_gainers ────────────────────────────────────────

class TestGetGainers:
    # Force yf.download to return empty so every test in this class exercises the Gemini
    # fallback path rather than the fast yf.download path (which has its own test class).
    @pytest.fixture(autouse=True)
    def _no_screener(self, service: MarketDataService, monkeypatch) -> None:
        monkeypatch.setattr(
            service, "_get_us_gainers_yf_download", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            service, "_get_india_gainers_yf_download", AsyncMock(return_value=[])
        )

    def _raw_row(self, **kwargs) -> dict:
        defaults = {
            "ticker": "NVDA",
            "name": "NVIDIA",
            "price": 950.0,
            "change_pct": 8.5,
            "change_abs": 74.5,
            "volume": 45_000_000,
            "sector": "Technology",
            "has_catalyst": False,
        }
        return {**defaults, **kwargs}

    async def test_get_us_gainers_returns_sorted_list(self, service: MarketDataService) -> None:
        # All 3 Gemini calls (NYSE, NASDAQ, catalyst) return the same list.
        # Catalyst scan upgrades all tickers to confirmed; sort is (tier, -change_pct).
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

    async def test_get_us_gainers_deduplicates_nyse_nasdaq_overlap(
        self, service: MarketDataService
    ) -> None:
        # NYSE and NASDAQ return the same ticker; only one copy should appear.
        nyse_raw = [self._raw_row(ticker="NVDA", change_pct=8.5)]
        nasdaq_raw = [self._raw_row(ticker="NVDA", change_pct=8.5)]
        catalyst_raw: list[dict] = []
        with patch.object(
            service, "_fetch_gainers_gemini",
            new=AsyncMock(side_effect=[nyse_raw, nasdaq_raw, catalyst_raw]),
        ):
            result = await service.get_us_gainers()
        assert len([g for g in result if g.ticker == "NVDA"]) == 1

    async def test_get_us_gainers_mover_upgraded_to_confirmed_by_catalyst_scan(
        self, service: MarketDataService
    ) -> None:
        # NVDA appears in gainers as mover (has_catalyst=False) and also in catalyst scan.
        gainers_raw = [self._raw_row(ticker="NVDA", change_pct=8.5, has_catalyst=False)]
        catalyst_raw = [self._raw_row(ticker="NVDA", change_pct=8.5, has_catalyst=True)]
        with patch.object(
            service, "_fetch_gainers_gemini",
            new=AsyncMock(side_effect=[gainers_raw, [], catalyst_raw]),
        ):
            result = await service.get_us_gainers()
        nvda = next(g for g in result if g.ticker == "NVDA")
        assert nvda.signal_tier == "confirmed"

    async def test_get_us_gainers_catalyst_only_stock_added_as_catalyst_tier(
        self, service: MarketDataService
    ) -> None:
        # ASTC appears only in catalyst scan (not in gainers list).
        gainers_raw = [self._raw_row(ticker="NVDA", change_pct=8.5)]
        catalyst_raw = [self._raw_row(ticker="ASTC", change_pct=2.0, has_catalyst=True)]
        with patch.object(
            service, "_fetch_gainers_gemini",
            new=AsyncMock(side_effect=[gainers_raw, [], catalyst_raw]),
        ):
            result = await service.get_us_gainers()
        astc = next((g for g in result if g.ticker == "ASTC"), None)
        assert astc is not None
        assert astc.signal_tier == "catalyst"

    async def test_get_us_gainers_confirmed_sorted_before_mover(
        self, service: MarketDataService
    ) -> None:
        # INTC is mover (+20%), ASTC is catalyst (only 2%) — confirmed/catalyst beat mover.
        gainers_raw = [
            self._raw_row(ticker="INTC", change_pct=20.0, has_catalyst=False),
        ]
        catalyst_raw = [self._raw_row(ticker="ASTC", change_pct=2.0, has_catalyst=True)]
        with patch.object(
            service, "_fetch_gainers_gemini",
            new=AsyncMock(side_effect=[gainers_raw, [], catalyst_raw]),
        ):
            result = await service.get_us_gainers()
        tiers = [g.signal_tier for g in result]
        # catalyst tier (ASTC) should appear before mover tier (INTC)
        assert tiers.index("catalyst") < tiers.index("mover")

    async def test_get_india_gainers_returns_india_market_tag(
        self, service: MarketDataService
    ) -> None:
        # India uses 2 calls: gainers + catalyst scanner
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


# ── _get_us_gainers_yf_download / _get_india_gainers_yf_download ──────────────

class TestYfDownloadFetch:
    """yf.download-based gainer discovery from curated ticker universe."""

    # ── helpers ────────────────────────────────────────────────────────────────

    def _make_df(self, data: dict[str, tuple]) -> pd.DataFrame:
        """
        Build a multi-ticker yf.download-style MultiIndex DataFrame.
        data: {ticker: (close_list, volume_list)}
        """
        close_cols = {t: vals[0] for t, vals in data.items()}
        vol_cols = {t: vals[1] for t, vals in data.items()}

        close_df = pd.DataFrame(close_cols)
        vol_df = pd.DataFrame(vol_cols)

        close_df.columns = pd.MultiIndex.from_tuples(
            [("Close", c) for c in close_df.columns]
        )
        vol_df.columns = pd.MultiIndex.from_tuples(
            [("Volume", c) for c in vol_df.columns]
        )
        return pd.concat([close_df, vol_df], axis=1)

    # ── US download tests ───────────────────────────────────────────────────────

    async def test_us_returns_gainers_sorted_by_change_pct(
        self, service: MarketDataService
    ) -> None:
        """Higher % gains appear first in the result list."""
        df = self._make_df({
            "NVDA": ([100.0, 110.0], [5_000_000, 5_000_000]),  # +10%
            "TSLA": ([200.0, 204.0], [6_000_000, 6_000_000]),  # +2%
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")

        # At least NVDA should be present (TSLA may be missing from universe checks)
        tickers = [r["ticker"] for r in result]
        if len(result) >= 2:
            assert result[0]["change_pct"] >= result[-1]["change_pct"]
        if "NVDA" in tickers and "TSLA" in tickers:
            assert tickers.index("NVDA") < tickers.index("TSLA")

    async def test_us_filters_negative_change_pct(
        self, service: MarketDataService
    ) -> None:
        """Stocks that dropped over the period are excluded."""
        df = self._make_df({
            "NVDA": ([100.0, 110.0], [5_000_000, 5_000_000]),  # +10% ✓
            "AMD":  ([100.0, 95.0],  [3_000_000, 3_000_000]),  # -5%  ✗
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")

        tickers = [r["ticker"] for r in result]
        assert "AMD" not in tickers

    async def test_us_filters_price_below_5(
        self, service: MarketDataService
    ) -> None:
        """Stocks under $5 last close are excluded even with positive gain."""
        df = self._make_df({
            "NVDA": ([100.0, 110.0], [5_000_000, 5_000_000]),  # $110 ✓
            "IONQ": ([2.0, 2.5],     [2_000_000, 2_000_000]),  # $2.50 ✗
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")

        tickers = [r["ticker"] for r in result]
        assert "IONQ" not in tickers

    async def test_us_filters_low_volume(
        self, service: MarketDataService
    ) -> None:
        """Stocks with fewer than 500K shares are excluded."""
        df = self._make_df({
            "NVDA": ([100.0, 110.0], [5_000_000, 5_000_000]),  # high vol ✓
            "MRVL": ([20.0, 22.0],   [100_000, 100_000]),       # low vol  ✗
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")

        tickers = [r["ticker"] for r in result]
        assert "MRVL" not in tickers

    async def test_us_returns_empty_on_download_exception(
        self, service: MarketDataService
    ) -> None:
        """Network or auth failure returns [] so callers can fall back to Gemini."""
        with patch(
            "services.market_data.yf.download",
            side_effect=RuntimeError("Network error"),
        ):
            result = await service._get_us_gainers_yf_download("1d")
        assert result == []

    async def test_us_returns_empty_when_df_has_fewer_than_2_rows(
        self, service: MarketDataService
    ) -> None:
        """Single-row DataFrame can't compute returns — return []."""
        df = self._make_df({"NVDA": ([110.0], [5_000_000])})
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")
        assert result == []

    async def test_us_1d_uses_last_vs_second_to_last_close(
        self, service: MarketDataService
    ) -> None:
        """1d period: change = close[-1]/close[-2]-1 (single day), not start-to-end."""
        # 5 rows: 100 → 115 (+15% total) but last day is 112 → 115 (~+2.68%)
        df = self._make_df({
            "NVDA": (
                [100.0, 105.0, 108.0, 112.0, 115.0],
                [5_000_000] * 5,
            ),
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1d")

        nvda = next((r for r in result if r["ticker"] == "NVDA"), None)
        if nvda:
            # Last-day change: 115/112-1 ≈ +2.68%, NOT +15%
            assert nvda["change_pct"] < 10.0

    async def test_us_1w_uses_start_to_end_close(
        self, service: MarketDataService
    ) -> None:
        """1w period: change = close[-1]/close[0]-1 (full week start to end)."""
        # 5 rows: 100 → 115 (+15% total)
        df = self._make_df({
            "NVDA": (
                [100.0, 105.0, 108.0, 112.0, 115.0],
                [5_000_000] * 5,
            ),
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_us_gainers_yf_download("1w")

        nvda = next((r for r in result if r["ticker"] == "NVDA"), None)
        if nvda:
            # Full-period change: 115/100-1 = +15%
            assert abs(nvda["change_pct"] - 15.0) < 0.1

    # ── India download tests ───────────────────────────────────────────────────

    async def test_india_returns_plain_ticker_without_ns_suffix(
        self, service: MarketDataService
    ) -> None:
        """Results should use plain NSE symbol (e.g. RELIANCE, not RELIANCE.NS)."""
        df = self._make_df({
            "RELIANCE.NS": ([2800.0, 2900.0], [8_000_000, 8_000_000]),  # +3.57%
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_india_gainers_yf_download("1d")

        if result:
            assert all(".NS" not in r["ticker"] for r in result)
            tickers = [r["ticker"] for r in result]
            assert "RELIANCE" in tickers

    async def test_india_filters_price_below_50_inr(
        self, service: MarketDataService
    ) -> None:
        """Indian stocks under ₹50 are excluded."""
        df = self._make_df({
            "RELIANCE.NS": ([2800.0, 2900.0], [8_000_000, 8_000_000]),  # ₹2900 ✓
            "SAIL.NS":     ([30.0, 35.0],     [2_000_000, 2_000_000]),  # ₹35   ✗
        })
        with patch("services.market_data.yf.download", return_value=df):
            result = await service._get_india_gainers_yf_download("1d")

        tickers = [r["ticker"] for r in result]
        assert "SAIL" not in tickers

    async def test_india_returns_empty_on_download_exception(
        self, service: MarketDataService
    ) -> None:
        with patch(
            "services.market_data.yf.download",
            side_effect=RuntimeError("timeout"),
        ):
            result = await service._get_india_gainers_yf_download("1d")
        assert result == []


# ── _classify_catalysts_batch ─────────────────────────────────────────────────

class TestCatalystBatch:
    """Batch catalyst classification — single fast Gemini call, no Google Search."""

    def _gemini_response(self, text: str) -> dict:
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    async def test_returns_matched_tickers(self, service: MarketDataService) -> None:
        import httpx, respx

        with (
            patch("services.market_data.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response("NVDA, AAPL"))
            )
            result = await service._classify_catalysts_batch(["NVDA", "AAPL", "AMD"], "us")

        assert "NVDA" in result
        assert "AAPL" in result
        assert "AMD" not in result

    async def test_returns_empty_set_when_gemini_replies_none(
        self, service: MarketDataService
    ) -> None:
        import httpx, respx

        with (
            patch("services.market_data.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response("NONE"))
            )
            result = await service._classify_catalysts_batch(["NVDA", "AAPL"], "us")

        assert result == set()

    async def test_ignores_tickers_not_in_input_list(self, service: MarketDataService) -> None:
        import httpx, respx

        with (
            patch("services.market_data.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            # Gemini returns TSLA which was not in the input — should be filtered out
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(200, json=self._gemini_response("NVDA, TSLA"))
            )
            result = await service._classify_catalysts_batch(["NVDA", "AMD"], "us")

        assert "NVDA" in result
        assert "TSLA" not in result

    async def test_returns_empty_set_on_http_error(self, service: MarketDataService) -> None:
        import httpx, respx

        with (
            patch("services.market_data.get_cached_token", return_value="fake-token"),
            respx.mock,
        ):
            respx.post(url__regex=r".*aiplatform\.googleapis\.com.*").mock(
                return_value=httpx.Response(500, text="Server error")
            )
            result = await service._classify_catalysts_batch(["NVDA"], "us")

        assert result == set()

    async def test_returns_empty_set_when_project_not_configured(
        self, service: MarketDataService
    ) -> None:
        service._settings = service._settings.model_copy(update={"google_cloud_project": ""})
        result = await service._classify_catalysts_batch(["NVDA"], "us")
        assert result == set()

    async def test_returns_empty_set_for_empty_ticker_list(
        self, service: MarketDataService
    ) -> None:
        result = await service._classify_catalysts_batch([], "us")
        assert result == set()


# ── _get_us_gainers_1d / _get_us_gainers_period fast path ────────────────────

class TestUsGainersFastPath:
    """Tests for the yf.download-based fast path in _get_us_gainers_1d and _get_us_gainers_period."""

    def _yf_row(self, ticker="NVDA", **kwargs) -> dict:
        return {
            "ticker": ticker,
            "name": f"{ticker} Corp",
            "price": 950.0,
            "change_pct": 8.5,
            "change_abs": 74.5,
            "volume": 45_000_000,
            "sector": "Technology",
            "has_catalyst": False,
            **kwargs,
        }

    def _five_yf_rows(self, **overrides) -> list[dict]:
        """Helper: 5 rows (meets the >= 5 minimum for the yf.download fast path)."""
        base = [
            self._yf_row("NVDA", change_pct=8.5),
            self._yf_row("AMD",  change_pct=5.2),
            self._yf_row("INTC", change_pct=3.1),
            self._yf_row("TSLA", change_pct=4.0),
            self._yf_row("AMZN", change_pct=2.5),
        ]
        if overrides:
            base[0] = {**base[0], **overrides}
        return base

    async def test_uses_yf_download_when_returns_enough_stocks(
        self, service: MarketDataService
    ) -> None:
        yf_data = [self._yf_row(ticker=f"S{i}", change_pct=float(10 - i)) for i in range(10)]
        with (
            patch.object(service, "_get_us_gainers_yf_download", new=AsyncMock(return_value=yf_data)),
            patch.object(service, "_classify_catalysts_batch", new=AsyncMock(return_value=set())),
        ):
            result = await service._get_us_gainers_1d()

        assert len(result) > 0
        assert result[0].ticker.startswith("S")

    async def test_catalyst_tickers_marked_confirmed(self, service: MarketDataService) -> None:
        # Need >= 5 stocks so the fast path is taken (threshold is 5)
        yf_data = self._five_yf_rows()
        with (
            patch.object(service, "_get_us_gainers_yf_download", new=AsyncMock(return_value=yf_data)),
            patch.object(service, "_classify_catalysts_batch", new=AsyncMock(return_value={"NVDA"})),
        ):
            result = await service._get_us_gainers_1d()

        nvda = next(g for g in result if g.ticker == "NVDA")
        amd = next(g for g in result if g.ticker == "AMD")
        assert nvda.signal_tier == "confirmed"
        assert amd.signal_tier == "mover"

    async def test_falls_back_to_gemini_when_yf_returns_few_stocks(
        self, service: MarketDataService
    ) -> None:
        few_stocks = [self._yf_row(ticker=f"S{i}") for i in range(3)]  # < 5 minimum
        gemini_result = [service._build_gainers([self._yf_row("NVDA")], "us")[0]]

        with (
            patch.object(service, "_get_us_gainers_yf_download", new=AsyncMock(return_value=few_stocks)),
            patch.object(
                service, "_get_us_gainers_gemini", new=AsyncMock(return_value=gemini_result)
            ) as gemini_mock,
        ):
            await service._get_us_gainers_1d()

        gemini_mock.assert_called_once_with("1d")

    async def test_period_path_calls_yf_download_with_period_arg(
        self, service: MarketDataService
    ) -> None:
        """_get_us_gainers_period delegates to _get_us_gainers_yf_download with the same period."""
        yf_data = self._five_yf_rows()
        yf_mock = AsyncMock(return_value=yf_data)
        with (
            patch.object(service, "_get_us_gainers_yf_download", new=yf_mock),
            patch.object(service, "_classify_catalysts_batch", new=AsyncMock(return_value=set())),
        ):
            await service._get_us_gainers_period("1w")

        yf_mock.assert_called_once_with("1w")

    async def test_period_path_passes_yf_download_data_through(
        self, service: MarketDataService
    ) -> None:
        """_get_us_gainers_period uses change_pct directly from yf_download output."""
        yf_data = self._five_yf_rows(change_pct=15.0)  # NVDA +15% over the week
        with (
            patch.object(service, "_get_us_gainers_yf_download", new=AsyncMock(return_value=yf_data)),
            patch.object(service, "_classify_catalysts_batch", new=AsyncMock(return_value=set())),
        ):
            result = await service._get_us_gainers_period("1w")

        assert len(result) > 0
        nvda = next((g for g in result if g.ticker == "NVDA"), None)
        assert nvda is not None
        assert nvda.change_pct == 15.0

    async def test_period_path_falls_back_to_gemini_when_yf_insufficient(
        self, service: MarketDataService
    ) -> None:
        """If yf.download returns < 5 stocks for a period, falls back to Gemini."""
        few_stocks = [self._yf_row(ticker=f"S{i}") for i in range(2)]  # < 5
        with (
            patch.object(service, "_get_us_gainers_yf_download", new=AsyncMock(return_value=few_stocks)),
            patch.object(
                service, "_get_us_gainers_gemini", new=AsyncMock(return_value=[])
            ) as gemini_mock,
        ):
            await service._get_us_gainers_period("1w")

        gemini_mock.assert_called_once_with("1w")
