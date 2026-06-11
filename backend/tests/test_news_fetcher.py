"""
Tests for NewsFetcher — covers the new parallel yfinance + NewsAPI fetch,
deduplication, and the _fetch_yf_news helper.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import NewsItem
from services.news_fetcher import NewsFetcher


def _make_settings(api_key: str = "test-key") -> MagicMock:
    s = MagicMock()
    s.news_api_key = api_key
    return s


def _item(title: str, source: str = "TestSource", ts: int = 1_700_000_000) -> NewsItem:
    return NewsItem(
        title=title,
        source=source,
        published_at=datetime.fromtimestamp(ts, tz=timezone.utc),
        url=f"https://example.com/{title[:10]}",
    )


# ── _fetch_yf_news ────────────────────────────────────────────────────────────

class TestFetchYfNews:
    @pytest.fixture
    def fetcher(self):
        return NewsFetcher(_make_settings())

    @pytest.mark.asyncio
    async def test_returns_news_items(self, fetcher):
        raw = [
            {
                "content": {
                    "title": "ASTC Approves Lunar Mining Initiative",
                    "provider": {"displayName": "GlobeNewswire"},
                    "pubDate": "2026-05-28T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/astc"},
                }
            }
        ]
        with patch("services.news_fetcher.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.news = raw
            result = await fetcher._fetch_yf_news("ASTC", limit=8)

        assert len(result) == 1
        assert result[0].title == "ASTC Approves Lunar Mining Initiative"
        assert result[0].source == "GlobeNewswire"

    @pytest.mark.asyncio
    async def test_handles_legacy_format(self, fetcher):
        """yfinance older format: flat dict with 'title' and 'providerPublishTime'."""
        raw = [
            {
                "title": "ASTC surges 500%",
                "publisher": "MoneyCheck",
                "providerPublishTime": 1_700_000_000,
                "link": "https://moneycheck.com/astc",
            }
        ]
        with patch("services.news_fetcher.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.news = raw
            result = await fetcher._fetch_yf_news("ASTC", limit=8)

        assert len(result) == 1
        assert result[0].title == "ASTC surges 500%"
        assert result[0].source == "MoneyCheck"

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self, fetcher):
        with patch("services.news_fetcher.yf.Ticker", side_effect=Exception("yf error")):
            result = await fetcher._fetch_yf_news("ASTC", limit=8)
        assert result == []

    @pytest.mark.asyncio
    async def test_skips_items_with_no_title(self, fetcher):
        raw = [{"content": {"title": "", "provider": {"displayName": "X"}}}]
        with patch("services.news_fetcher.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.news = raw
            result = await fetcher._fetch_yf_news("ASTC", limit=8)
        assert result == []


# ── get_news (merged) ─────────────────────────────────────────────────────────

class TestGetNews:
    @pytest.fixture
    def fetcher(self):
        return NewsFetcher(_make_settings())

    @pytest.mark.asyncio
    async def test_deduplicates_same_title_across_sources(self, fetcher):
        """Same title from yfinance and NewsAPI should only appear once."""
        shared = _item("ASTC Approves Lunar Mining")
        newsapi_items = [shared, _item("Unrelated Article")]
        yf_items = [shared]  # duplicate

        fetcher._fetch_newsapi = AsyncMock(return_value=newsapi_items)  # type: ignore[method-assign]
        fetcher._fetch_yf_news = AsyncMock(return_value=yf_items)       # type: ignore[method-assign]

        result = await fetcher.get_news("ASTC", "Astrotech Corporation")
        titles = [r.title for r in result]
        assert titles.count("ASTC Approves Lunar Mining") == 1

    @pytest.mark.asyncio
    async def test_merges_items_from_both_sources(self, fetcher):
        # Titles must mention ticker/company — the relevance filter requires it
        newsapi_items = [_item("ASTC closes government contract deal", ts=1_700_001_000)]
        yf_items      = [_item("Astrotech reports Q3 earnings beat",   ts=1_700_002_000)]

        fetcher._fetch_newsapi = AsyncMock(return_value=newsapi_items)  # type: ignore[method-assign]
        fetcher._fetch_yf_news = AsyncMock(return_value=yf_items)       # type: ignore[method-assign]

        result = await fetcher.get_news("ASTC", "Astrotech")
        assert len(result) == 2
        # Most recent first
        assert result[0].title == "Astrotech reports Q3 earnings beat"

    @pytest.mark.asyncio
    async def test_still_returns_items_if_newsapi_fails(self, fetcher):
        yf_items = [_item("ASTC surges on contract win")]

        fetcher._fetch_newsapi = AsyncMock(side_effect=Exception("newsapi down"))  # type: ignore[method-assign]
        fetcher._fetch_yf_news = AsyncMock(return_value=yf_items)                  # type: ignore[method-assign]

        result = await fetcher.get_news("ASTC", "Astrotech")
        assert len(result) == 1
        assert result[0].title == "ASTC surges on contract win"

    @pytest.mark.asyncio
    async def test_uses_google_rss_fallback_when_no_api_key(self):
        fetcher = NewsFetcher(_make_settings(api_key=""))
        rss_items = [_item("ASTC Google RSS headline")]
        yf_items  = [_item("Astrotech YF news item")]

        fetcher._fetch_google_news_rss = AsyncMock(return_value=rss_items)  # type: ignore[method-assign]
        fetcher._fetch_yf_news         = AsyncMock(return_value=yf_items)   # type: ignore[method-assign]

        result = await fetcher.get_news("ASTC", "Astrotech")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_respects_limit(self, fetcher):
        many = [_item(f"ASTC update {i}", ts=1_700_000_000 + i) for i in range(10)]
        fetcher._fetch_newsapi = AsyncMock(return_value=many)  # type: ignore[method-assign]
        fetcher._fetch_yf_news = AsyncMock(return_value=[])    # type: ignore[method-assign]

        result = await fetcher.get_news("ASTC", "Astrotech", limit=5)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_filters_unrelated_articles(self, fetcher):
        """Articles that don't mention the ticker or company must be dropped."""
        relevant   = _item("ASTC wins NASA subcontract")
        irrelevant = _item("Egg freezing is a booming business in Canada")

        fetcher._fetch_newsapi = AsyncMock(return_value=[relevant, irrelevant])
        fetcher._fetch_yf_news = AsyncMock(return_value=[])

        result = await fetcher.get_news("ASTC", "Astrotech")
        assert len(result) == 1
        assert result[0].title == "ASTC wins NASA subcontract"
