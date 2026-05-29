"""
Tests for the Catalyst Scanner feature.

Covers:
  - Momentum score computation
  - Catalyst type classification
  - Signal tier assignment
  - CatalystPlay schema validation
  - CatalystScannerService.scan() — mocked dependencies
  - GET /api/catalyst/{market} endpoint — mock AI, no real HTTP
  - Consistency assertions: no empty verdicts, scores in range, signals valid
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.schemas import CatalystPlay, CatalystScanResponse, Market
from services.catalyst_scanner import (
    CatalystScannerService,
    _classify_catalyst_type,
    _compute_momentum_score,
    _extract_catalyst_headline,
    _score_to_signal,
)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — pure functions
# ─────────────────────────────────────────────────────────────────────────────

class TestMomentumScore:
    def test_high_score_with_catalyst_and_big_volume(self) -> None:
        score = _compute_momentum_score(25.0, 5.0, has_catalyst=True)
        assert score == 100.0  # 40 + 40 + 20

    def test_no_catalyst_lowers_score(self) -> None:
        without = _compute_momentum_score(20.0, 3.0, has_catalyst=False)
        with_cat = _compute_momentum_score(20.0, 3.0, has_catalyst=True)
        assert with_cat - without == 20.0

    def test_unknown_volume_gives_partial_credit(self) -> None:
        score = _compute_momentum_score(10.0, None, has_catalyst=False)
        assert score > 0  # partial credit given

    def test_small_move_low_volume_no_catalyst_is_low(self) -> None:
        score = _compute_momentum_score(1.0, 0.8, has_catalyst=False)
        assert score < 30

    def test_score_never_exceeds_100(self) -> None:
        score = _compute_momentum_score(200.0, 100.0, has_catalyst=True)
        assert score <= 100.0

    def test_score_never_negative(self) -> None:
        score = _compute_momentum_score(0.5, 0.3, has_catalyst=False)
        assert score >= 0.0


class TestSignalTier:
    def test_strong_move_at_60(self) -> None:
        assert _score_to_signal(60.0) == "strong_move"

    def test_emerging_at_30(self) -> None:
        assert _score_to_signal(30.0) == "emerging"

    def test_noise_below_30(self) -> None:
        assert _score_to_signal(29.9) == "noise"

    def test_score_100_is_strong(self) -> None:
        assert _score_to_signal(100.0) == "strong_move"

    def test_score_0_is_noise(self) -> None:
        assert _score_to_signal(0.0) == "noise"


class TestCatalystTypeClassification:
    def test_fda_keywords(self) -> None:
        assert _classify_catalyst_type(["FDA approves new drug treatment"]) == "fda_approval"

    def test_earnings_keywords(self) -> None:
        assert _classify_catalyst_type(["NVDA earnings beat consensus by 15%"]) == "earnings"

    def test_acquisition_keywords(self) -> None:
        assert _classify_catalyst_type(["Company acquires rival for $2B"]) == "acquisition"

    def test_government_contract(self) -> None:
        result = _classify_catalyst_type(["ASTC wins NASA lunar surface contract"])
        assert result == "regulatory"

    def test_partnership(self) -> None:
        result = _classify_catalyst_type(["Microsoft signs strategic deal with OpenAI"])
        assert result == "partnership"

    def test_unknown_for_generic_headlines(self) -> None:
        result = _classify_catalyst_type(["Stock moves higher in volatile session"])
        assert result == "unknown"

    def test_empty_headlines_returns_unknown(self) -> None:
        assert _classify_catalyst_type([]) == "unknown"


class TestExtractCatalystHeadline:
    def test_returns_none_for_empty(self) -> None:
        assert _extract_catalyst_headline([]) is None

    def test_returns_catalyst_headline_over_generic(self) -> None:
        headlines = [
            "Stock up 3% in thin trading",
            "ASTC wins NASA contract worth $12M",
        ]
        result = _extract_catalyst_headline(headlines)
        assert result is not None
        assert "NASA" in result or "ASTC" in result

    def test_truncates_long_headline(self) -> None:
        long = "X" * 200
        headlines = [long]
        result = _extract_catalyst_headline(headlines)
        assert result is not None
        assert len(result) <= 120


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalystPlaySchema:
    def test_valid_play(self) -> None:
        play = CatalystPlay(
            ticker="ASTC",
            name="Astrotech Corporation",
            market="us",
            sector="Industrials",
            price=6.55,
            change_pct=147.2,
            change_abs=3.91,
            volume=5_200_000,
            avg_volume=1_000_000,
            volume_ratio=5.2,
            momentum_score=100.0,
            catalyst_type="regulatory",
            signal="strong_move",
            headline_catalyst="Astrotech wins NASA lunar contract",
            ai_verdict="ASTC surged after winning a NASA lunar surface contract.",
        )
        assert play.ticker == "ASTC"
        assert play.signal == "strong_move"
        assert play.momentum_score == 100.0

    def test_optional_fields_default_none(self) -> None:
        play = CatalystPlay(
            ticker="XYZ",
            name="Test Corp",
            market="us",
            price=10.0,
            change_pct=5.0,
            change_abs=0.5,
            volume=100_000,
            momentum_score=35.0,
            catalyst_type="unknown",
            signal="emerging",
        )
        assert play.avg_volume is None
        assert play.volume_ratio is None
        assert play.headline_catalyst is None


class TestCatalystScanResponse:
    def test_empty_plays(self) -> None:
        r = CatalystScanResponse(market="us", plays=[])
        assert r.plays == []
        assert r.from_cache is False

    def test_with_plays(self) -> None:
        play = CatalystPlay(
            ticker="NVDA", name="NVIDIA", market="us",
            price=900.0, change_pct=8.2, change_abs=68.0,
            volume=45_000_000, avg_volume=20_000_000,
            volume_ratio=2.25, momentum_score=77.0,
            catalyst_type="earnings", signal="strong_move",
        )
        r = CatalystScanResponse(market="us", plays=[play])
        assert len(r.plays) == 1
        assert r.plays[0].ticker == "NVDA"


# ─────────────────────────────────────────────────────────────────────────────
# Service tests — mocked dependencies
# ─────────────────────────────────────────────────────────────────────────────

def _make_raw_movers(n: int = 5, market: str = "us") -> list[dict[str, Any]]:
    """Generate n synthetic raw mover dicts matching screener output format."""
    tickers = ["ASTC", "NVDA", "AAPL", "MSFT", "TSLA", "META", "AMZN", "GOOG"]
    return [
        {
            "ticker": tickers[i % len(tickers)],
            "name": f"Company {i}",
            "price": 50.0 + i * 10,
            "change_pct": 20.0 - i * 2,  # 20, 18, 16, ...
            "change_abs": 5.0 - i * 0.5,
            "volume": 5_000_000 - i * 500_000,
            "sector": "Technology",
            "has_catalyst": False,
        }
        for i in range(n)
    ]


def _make_scanner(mock_ai: bool = True) -> CatalystScannerService:
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.mock_ai = mock_ai
    settings.google_cloud_project = "test-project"
    settings.google_cloud_region = "us-central1"
    settings.vertex_ai_model_flash = "gemini-2.0-flash-001"

    market_data = MagicMock()
    news_fetcher = MagicMock()
    analyst = MagicMock()
    analyst.analyse = AsyncMock(return_value={})

    scanner = CatalystScannerService(settings, market_data, news_fetcher, analyst)
    return scanner


@pytest.mark.asyncio
async def test_scan_returns_plays_for_us() -> None:
    scanner = _make_scanner()
    raw_movers = _make_raw_movers(5)

    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    scanner._fetch_avg_volumes = AsyncMock(return_value={
        r["ticker"]: 2_000_000.0 for r in raw_movers
    })
    scanner._fetch_batch_headlines = AsyncMock(return_value={
        r["ticker"]: ["Earnings beat consensus", "Stock surges on results"]
        for r in raw_movers
    })
    scanner._analyst.analyse = AsyncMock(return_value={
        r["ticker"]: f"Mock verdict for {r['ticker']}." for r in raw_movers
    })

    response = await scanner.scan("us")

    assert isinstance(response, CatalystScanResponse)
    assert len(response.plays) > 0
    assert response.from_cache is False


@pytest.mark.asyncio
async def test_scan_returns_empty_when_no_movers() -> None:
    scanner = _make_scanner()
    scanner._market_data.get_raw_movers = AsyncMock(return_value=[])

    response = await scanner.scan("us")

    assert response.plays == []


@pytest.mark.asyncio
async def test_scan_plays_sorted_by_momentum_score() -> None:
    scanner = _make_scanner()
    raw_movers = _make_raw_movers(5)

    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    scanner._fetch_avg_volumes = AsyncMock(return_value={
        r["ticker"]: 1_000_000.0 for r in raw_movers
    })
    scanner._fetch_batch_headlines = AsyncMock(return_value={
        r["ticker"]: [] for r in raw_movers
    })
    scanner._analyst.analyse = AsyncMock(return_value={
        r["ticker"]: "verdict" for r in raw_movers
    })

    response = await scanner.scan("us")
    scores = [p.momentum_score for p in response.plays]
    assert scores == sorted(scores, reverse=True), "Plays must be sorted by momentum_score desc"


@pytest.mark.asyncio
async def test_scan_all_plays_have_valid_signal() -> None:
    scanner = _make_scanner()
    raw_movers = _make_raw_movers(8)

    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    scanner._fetch_avg_volumes = AsyncMock(return_value={
        r["ticker"]: 1_000_000.0 for r in raw_movers
    })
    scanner._fetch_batch_headlines = AsyncMock(return_value={
        r["ticker"]: [] for r in raw_movers
    })
    scanner._analyst.analyse = AsyncMock(return_value={
        r["ticker"]: "Mock verdict." for r in raw_movers
    })

    response = await scanner.scan("us")

    valid_signals = {"strong_move", "emerging", "noise"}
    for play in response.plays:
        assert play.signal in valid_signals, f"{play.ticker} has invalid signal: {play.signal}"


@pytest.mark.asyncio
async def test_scan_momentum_scores_in_range() -> None:
    scanner = _make_scanner()
    raw_movers = _make_raw_movers(8)

    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    scanner._fetch_avg_volumes = AsyncMock(return_value={
        r["ticker"]: 500_000.0 for r in raw_movers
    })
    scanner._fetch_batch_headlines = AsyncMock(return_value={
        r["ticker"]: ["FDA approves new treatment"] for r in raw_movers
    })
    scanner._analyst.analyse = AsyncMock(return_value={
        r["ticker"]: "Verdict." for r in raw_movers
    })

    response = await scanner.scan("us")
    for play in response.plays:
        assert 0.0 <= play.momentum_score <= 100.0, (
            f"{play.ticker} score {play.momentum_score} out of range"
        )


@pytest.mark.asyncio
async def test_scan_india_market() -> None:
    scanner = _make_scanner()
    raw_movers = [
        {"ticker": "RELIANCE", "name": "Reliance Industries", "price": 2800.0,
         "change_pct": 5.2, "change_abs": 140.0, "volume": 8_000_000, "sector": "Energy",
         "has_catalyst": False},
        {"ticker": "TCS", "name": "TCS", "price": 3600.0,
         "change_pct": 3.1, "change_abs": 108.0, "volume": 3_000_000, "sector": "Technology",
         "has_catalyst": False},
    ]
    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    scanner._fetch_avg_volumes = AsyncMock(return_value={"RELIANCE": 4_000_000.0, "TCS": 2_000_000.0})
    scanner._fetch_batch_headlines = AsyncMock(return_value={
        "RELIANCE": ["Reliance wins major government contract"],
        "TCS": ["TCS signs partnership with European bank"],
    })
    scanner._analyst.analyse = AsyncMock(return_value={
        "RELIANCE": "Reliance won a major state contract.",
        "TCS": "TCS signed a new deal.",
    })

    response = await scanner.scan("india")
    assert len(response.plays) == 2
    assert response.market == "india"


@pytest.mark.asyncio
async def test_scan_volume_ratio_computed_correctly() -> None:
    scanner = _make_scanner()
    raw_movers = [
        {"ticker": "ASTC", "name": "Astrotech", "price": 6.55,
         "change_pct": 147.0, "change_abs": 3.91, "volume": 5_200_000,
         "sector": "Industrials", "has_catalyst": False},
    ]
    scanner._market_data.get_raw_movers = AsyncMock(return_value=raw_movers)
    # Avg volume = 1M → ratio should be 5.2
    scanner._fetch_avg_volumes = AsyncMock(return_value={"ASTC": 1_000_000.0})
    scanner._fetch_batch_headlines = AsyncMock(return_value={"ASTC": ["NASA contract win"]})
    scanner._analyst.analyse = AsyncMock(return_value={"ASTC": "ASTC won a NASA contract."})

    response = await scanner.scan("us")
    play = response.plays[0]
    assert play.ticker == "ASTC"
    assert play.volume_ratio == 5.2
    assert play.avg_volume == 1_000_000


# ─────────────────────────────────────────────────────────────────────────────
# API endpoint tests — TestClient with mocked scanner
# ─────────────────────────────────────────────────────────────────────────────

def _make_play(ticker: str = "ASTC", signal: str = "strong_move") -> CatalystPlay:
    return CatalystPlay(
        ticker=ticker,
        name=f"{ticker} Corp",
        market="us",
        sector="Technology",
        price=10.0,
        change_pct=50.0,
        change_abs=3.3,
        volume=5_000_000,
        avg_volume=1_000_000,
        volume_ratio=5.0,
        momentum_score=95.0,
        catalyst_type="regulatory",
        signal=signal,
        headline_catalyst="Company wins major government contract",
        ai_verdict="The move is driven by a government contract win. Watch for follow-through volume tomorrow.",
    )


@pytest.fixture()
def test_client() -> TestClient:
    """TestClient with mock_ai=True so no real Gemini/GCP calls are made."""
    import os
    os.environ["MOCK_AI"] = "true"
    from main import create_app
    app = create_app()
    return TestClient(app)


def test_catalyst_endpoint_us(test_client: TestClient) -> None:
    mock_response = CatalystScanResponse(
        market="us",
        plays=[_make_play("ASTC"), _make_play("NVDA", "emerging")],
    )
    with patch(
        "api.routes.catalyst.CatalystScannerService.scan",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        # Patch the scanner singleton directly
        with patch("api.deps.get_catalyst_scanner") as mock_get_scanner:
            mock_scanner = MagicMock()
            mock_scanner.scan = AsyncMock(return_value=mock_response)
            mock_get_scanner.return_value = mock_scanner

            resp = test_client.get("/api/catalyst/us")

    assert resp.status_code == 200
    data = resp.json()
    assert data["market"] == "us"
    assert "plays" in data


def test_catalyst_endpoint_india(test_client: TestClient) -> None:
    mock_response = CatalystScanResponse(
        market="india",
        plays=[
            CatalystPlay(
                ticker="RELIANCE", name="Reliance Industries", market="india",
                price=2800.0, change_pct=5.2, change_abs=140.0, volume=8_000_000,
                avg_volume=4_000_000, volume_ratio=2.0, momentum_score=67.0,
                catalyst_type="regulatory", signal="strong_move",
                ai_verdict="Reliance won a state energy contract.",
            )
        ],
    )
    with patch("api.deps.get_catalyst_scanner") as mock_get_scanner:
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_response)
        mock_get_scanner.return_value = mock_scanner

        resp = test_client.get("/api/catalyst/india")

    assert resp.status_code == 200
    data = resp.json()
    assert data["market"] == "india"


def test_catalyst_endpoint_cache_hit(test_client: TestClient) -> None:
    """When cache has data, scanner.scan should NOT be called."""
    cached_data = CatalystScanResponse(
        market="us",
        plays=[_make_play()],
        from_cache=False,
    ).model_dump()

    with patch("api.deps.get_catalyst_scanner") as mock_get_scanner, \
         patch("api.deps.get_cache") as mock_get_cache:

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=cached_data)
        mock_get_cache.return_value = mock_cache

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(side_effect=AssertionError("scan should not be called on cache hit"))
        mock_get_scanner.return_value = mock_scanner

        resp = test_client.get("/api/catalyst/us")

    # Cache hit serves 200; scanner not invoked (no AssertionError raised)
    assert resp.status_code == 200


def test_catalyst_endpoint_invalid_market(test_client: TestClient) -> None:
    resp = test_client.get("/api/catalyst/japan")
    assert resp.status_code == 422  # FastAPI validation error


# ─────────────────────────────────────────────────────────────────────────────
# Consistency / regression tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConsistency:
    """Catch the class of bugs the user reported: things that sometimes work
    and sometimes don't, or return silent defaults."""

    def test_strong_move_implies_high_score(self) -> None:
        """If signal is strong_move, score must be >= 60."""
        for vol_ratio in [2.0, 3.0, 5.0]:
            score = _compute_momentum_score(15.0, vol_ratio, has_catalyst=True)
            signal = _score_to_signal(score)
            assert signal == "strong_move", (
                f"vol_ratio={vol_ratio} → score={score} → signal={signal}, expected strong_move"
            )

    def test_noise_signal_means_low_score(self) -> None:
        score = _compute_momentum_score(1.0, 0.5, has_catalyst=False)
        assert _score_to_signal(score) == "noise"

    def test_catalyst_bonus_always_20_pts(self) -> None:
        base = _compute_momentum_score(10.0, 2.0, has_catalyst=False)
        with_cat = _compute_momentum_score(10.0, 2.0, has_catalyst=True)
        assert with_cat - base == 20.0

    def test_volume_ratio_none_does_not_crash(self) -> None:
        score = _compute_momentum_score(10.0, None, has_catalyst=True)
        assert isinstance(score, float)

    def test_all_catalyst_types_are_valid_literals(self) -> None:
        """Every _classify_catalyst_type result must be a valid CatalystType."""
        from models.schemas import CatalystType
        import typing
        valid = set(typing.get_args(CatalystType))
        test_cases = [
            ["FDA approves drug"],
            ["Company acquires rival"],
            ["Earnings beat"],
            ["NASA contract awarded"],
            ["Partnership signed"],
            ["Analyst upgrades stock"],
            ["Fed rate decision"],
            [],
        ]
        for headlines in test_cases:
            result = _classify_catalyst_type(headlines)
            assert result in valid, f"Invalid catalyst type: {result}"
