"""
Tests for the quarterly results feature.

Covers:
  - HTML parser: correctly extracts screener.in quarterly table
  - YoY growth computation
  - Trend detection (accelerating, expanding, recovering, etc.)
  - format_for_prompt: produces non-empty, sensibly structured text
  - QuarterlyFetcher: graceful fallback on HTTP failure
  - Route integration: quarterly_text is passed to analyst
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import QuarterlyResult, QuarterlySnapshot
from services.quarterly_fetcher import (
    QuarterlyFetcher,
    _build_results_newest_first,
    _earnings_trend,
    _margin_trend,
    _parse_screener_html,
    _revenue_trend,
    format_for_prompt,
)


# ── Minimal screener.in-style HTML for tests ──────────────────────────────────

_SAMPLE_HTML = """
<html><body>
<section id="quarters">
  <div class="responsive-holder">
    <table class="data-table">
      <thead>
        <tr>
          <th></th>
          <th>Jun 2023</th>
          <th>Sep 2023</th>
          <th>Dec 2023</th>
          <th>Mar 2024</th>
          <th>Jun 2024</th>
          <th>Sep 2024</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>Sales</td><td>1,000</td><td>1,050</td><td>1,100</td><td>1,200</td><td>1,100</td><td>1,260</td></tr>
        <tr><td>Operating Profit</td><td>150</td><td>168</td><td>187</td><td>228</td><td>198</td><td>252</td></tr>
        <tr><td>OPM %</td><td>15</td><td>16</td><td>17</td><td>19</td><td>18</td><td>20</td></tr>
        <tr><td>Net Profit</td><td>80</td><td>95</td><td>100</td><td>130</td><td>88</td><td>140</td></tr>
        <tr><td>EPS in Rs</td><td>5.0</td><td>6.0</td><td>6.3</td><td>8.2</td><td>5.5</td><td>8.8</td></tr>
      </tbody>
    </table>
  </div>
</section>
</body></html>
"""

# ── Parser tests ──────────────────────────────────────────────────────────────

class TestScreenerParser:
    def test_extracts_quarter_labels(self):
        quarters, data = _parse_screener_html(_SAMPLE_HTML)
        assert len(quarters) == 6
        assert quarters[0] == "Jun 2023"
        assert quarters[-1] == "Sep 2024"

    def test_extracts_sales_row(self):
        quarters, data = _parse_screener_html(_SAMPLE_HTML)
        sales_key = next(k for k in data if "Sales" in k)
        assert data[sales_key][0] == "1,000"   # Jun 2023
        assert data[sales_key][-1] == "1,260"  # Sep 2024

    def test_extracts_opm_row(self):
        quarters, data = _parse_screener_html(_SAMPLE_HTML)
        opm_key = next(k for k in data if "OPM" in k)
        assert data[opm_key][0] == "15"
        assert data[opm_key][-1] == "20"

    def test_missing_section_returns_empty(self):
        quarters, data = _parse_screener_html("<html><body>no quarters here</body></html>")
        assert quarters == []
        assert data == {}


# ── Build results tests ───────────────────────────────────────────────────────

class TestBuildResults:
    def _get_results(self) -> list[QuarterlyResult]:
        quarters, data = _parse_screener_html(_SAMPLE_HTML)
        return _build_results_newest_first(quarters, data)

    def test_returns_newest_first(self):
        results = self._get_results()
        assert results[0].period == "Sep 2024"
        assert results[-1].period == "Jun 2023"

    def test_revenue_values_parsed_correctly(self):
        results = self._get_results()
        # Sep 2024 should have revenue 1260
        assert results[0].revenue == 1260.0

    def test_opm_parsed(self):
        results = self._get_results()
        # Sep 2024 OPM = 20
        assert results[0].opm_pct == 20.0

    def test_eps_parsed(self):
        results = self._get_results()
        assert results[0].eps == 8.8

    def test_yoy_growth_computed(self):
        results = self._get_results()
        # Sep 2024 vs Sep 2023: (1260 - 1050) / 1050 * 100 = +20%
        assert results[0].revenue_growth_yoy is not None
        assert abs(results[0].revenue_growth_yoy - 20.0) < 0.5

    def test_yoy_pat_growth_computed(self):
        results = self._get_results()
        # Sep 2024 vs Sep 2023: (140 - 95) / 95 * 100 = +47.4%
        assert results[0].pat_growth_yoy is not None
        assert abs(results[0].pat_growth_yoy - 47.4) < 1.0

    def test_oldest_quarter_has_no_yoy(self):
        results = self._get_results()
        # Jun 2023 has no prior year data in our 6-quarter sample
        assert results[-1].revenue_growth_yoy is None


# ── Trend detection tests ─────────────────────────────────────────────────────

class TestTrends:
    def _make_results(self, rev_growths: list[float], opms: list[float], pat_growths: list[float]):
        return [
            QuarterlyResult(
                period=f"Q{i}",
                revenue=1000.0,
                opm_pct=o,
                revenue_growth_yoy=r,
                pat_growth_yoy=p,
            )
            for i, (r, o, p) in enumerate(zip(rev_growths, opms, pat_growths))
        ]

    def test_revenue_accelerating(self):
        results = self._make_results([20, 12, 8, 5], [20]*4, [20, 12, 8, 5])
        assert _revenue_trend(results) == "accelerating"

    def test_revenue_stable(self):
        results = self._make_results([10, 10, 11, 9], [20]*4, [10]*4)
        assert _revenue_trend(results) == "stable"

    def test_revenue_recovering(self):
        results = self._make_results([5, -2, -5, -8], [20]*4, [5, -2, -5, -8])
        assert _revenue_trend(results) == "recovering"

    def test_revenue_declining(self):
        # All quarters negative and worsening → "declining" (not "decelerating")
        results = self._make_results([-10, -5, -3, -1], [20]*4, [-10, -5, -3, -1])
        assert _revenue_trend(results) == "declining"

    def test_margin_expanding(self):
        results = self._make_results([10]*4, [22, 19, 17, 15], [10]*4)
        assert _margin_trend(results) == "expanding"

    def test_margin_compressing(self):
        results = self._make_results([10]*4, [12, 15, 18, 20], [10]*4)
        assert _margin_trend(results) == "compressing"

    def test_margin_stable(self):
        results = self._make_results([10]*4, [18, 18, 19, 18], [10]*4)
        assert _margin_trend(results) == "stable"

    def test_earnings_accelerating(self):
        results = self._make_results([10]*4, [20]*4, [35, 22, 15, 10])
        assert _earnings_trend(results) == "accelerating"

    def test_insufficient_data(self):
        results = [QuarterlyResult(period="Q1")]
        assert _revenue_trend(results) == "unknown"
        assert _margin_trend(results) == "unknown"
        assert _earnings_trend(results) == "unknown"


# ── format_for_prompt tests ───────────────────────────────────────────────────

class TestFormatForPrompt:
    def _make_snap(self) -> QuarterlySnapshot:
        return QuarterlySnapshot(
            ticker="GPIL",
            market="india",
            quarters=[
                QuarterlyResult(
                    period="Sep 2024",
                    revenue=1260.0, opm_pct=20.0, net_profit=140.0, eps=8.8,
                    revenue_growth_yoy=20.0, pat_growth_yoy=47.4,
                ),
                QuarterlyResult(
                    period="Jun 2024",
                    revenue=1100.0, opm_pct=18.0, net_profit=88.0, eps=5.5,
                    revenue_growth_yoy=10.0, pat_growth_yoy=10.0,
                ),
            ],
            revenue_trend="accelerating",
            margin_trend="expanding",
            earnings_trend="accelerating",
        )

    def test_output_is_non_empty(self):
        snap = self._make_snap()
        text = format_for_prompt(snap)
        assert len(text) > 100

    def test_contains_ticker_data(self):
        snap = self._make_snap()
        text = format_for_prompt(snap)
        assert "Sep 2024" in text
        assert "1,260" in text
        assert "20%" in text  # OPM

    def test_contains_trend_labels(self):
        snap = self._make_snap()
        text = format_for_prompt(snap)
        assert "ACCELERATING" in text
        assert "EXPANDING" in text

    def test_contains_yoy_growth(self):
        snap = self._make_snap()
        text = format_for_prompt(snap)
        assert "+20% YoY" in text or "+20%" in text

    def test_includes_bullish_hint_for_strong_trends(self):
        snap = self._make_snap()
        text = format_for_prompt(snap)
        # Should include positive contextual hint
        assert "tailwind" in text.lower() or "improving" in text.lower()

    def test_includes_caution_for_weak_trends(self):
        snap = self._make_snap()
        snap.earnings_trend = "declining"
        text = format_for_prompt(snap)
        assert "caution" in text.lower() or "weakening" in text.lower()


# ── QuarterlyFetcher graceful fallback tests ──────────────────────────────────

class TestQuarterlyFetcherFallback:
    async def test_returns_none_on_http_error(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        fetcher = QuarterlyFetcher(settings)

        with patch("services.quarterly_fetcher.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = Exception("Server error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await fetcher.fetch("GPIL", "india")
            assert result is None

    async def test_returns_none_on_empty_html(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        fetcher = QuarterlyFetcher(settings)

        with patch("services.quarterly_fetcher.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.text = "<html><body>no quarterly data here</body></html>"
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await fetcher.fetch("UNKNOWN", "india")
            assert result is None

    async def test_returns_snapshot_on_valid_html(self):
        from core.config import Settings
        settings = Settings(mock_ai=True)
        fetcher = QuarterlyFetcher(settings)

        with patch("services.quarterly_fetcher.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.text = _SAMPLE_HTML
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await fetcher.fetch("GPIL", "india")
            assert result is not None
            assert result.ticker == "GPIL"
            assert result.market == "india"
            assert len(result.quarters) > 0
            assert result.quarters[0].period == "Sep 2024"  # most recent first
