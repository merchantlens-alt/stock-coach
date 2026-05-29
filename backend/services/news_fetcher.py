from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import Settings
from core.exceptions import NewsError
from core.logging import get_logger
from models.schemas import NewsItem

log = get_logger(__name__)

_NEWSAPI_BASE = "https://newsapi.org/v2/everything"
_NEWSAPI_HEADLINES = "https://newsapi.org/v2/top-headlines"
_GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# Broad baskets used for Radar yfinance fallback — major tickers whose news
# reflects macro themes rather than single-stock events.
_US_RADAR_BASKET = ["SPY", "QQQ", "NVDA", "MSFT", "AAPL", "JPM", "XLK", "XLE"]
_IN_RADAR_BASKET = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "NIFTYBEES.NS"]


class NewsFetcher:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.news_api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_news(self, ticker: str, company_name: str, limit: int = 8) -> list[NewsItem]:
        """
        Fetch recent news for a ticker.
        Runs NewsAPI/Google News RSS + yfinance Yahoo Finance news in parallel,
        deduplicates by title, and returns the most recent `limit` articles.
        yfinance news has broader coverage of stock-moving events (press releases,
        earnings, FDA, government contracts) that NewsAPI often misses.
        """
        tasks = [self._fetch_yf_news(ticker, limit)]
        if self._api_key:
            tasks.append(self._fetch_newsapi(ticker, company_name, limit))
        else:
            tasks.append(self._fetch_google_news_rss(ticker, company_name, limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_titles: set[str] = set()
        merged: list[NewsItem] = []
        for batch in results:
            if isinstance(batch, Exception):
                continue
            for item in batch:
                key = item.title.lower()[:60]
                if key not in seen_titles:
                    seen_titles.add(key)
                    merged.append(item)

        # Sort by recency (None published_at goes last), return top limit
        merged.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return merged[:limit]

    async def _fetch_yf_news(self, ticker: str, limit: int) -> list[NewsItem]:
        """
        Fetch news from yfinance (Yahoo Finance) — no API key needed.
        Handles both US tickers and NSE tickers (with/without .NS suffix).
        """
        try:
            raw = await asyncio.to_thread(lambda: yf.Ticker(ticker).news)
            items: list[NewsItem] = []
            for item in (raw or [])[:limit]:
                content = item.get("content", {})
                title = content.get("title") or item.get("title", "")
                publisher = (
                    content.get("provider", {}).get("displayName")
                    or item.get("publisher", "Yahoo Finance")
                )
                pub_time = content.get("pubDate") or item.get("providerPublishTime")
                url = (
                    content.get("canonicalUrl", {}).get("url")
                    or item.get("link")
                )
                if isinstance(pub_time, (int, float)):
                    published_at = datetime.fromtimestamp(pub_time, tz=timezone.utc)
                elif isinstance(pub_time, str):
                    published_at = _parse_dt(pub_time)
                else:
                    published_at = None
                if title:
                    items.append(NewsItem(
                        title=title,
                        source=publisher,
                        published_at=published_at,
                        url=url or None,
                    ))
            log.info("news.yf_news_done", ticker=ticker, count=len(items))
            return items
        except Exception as exc:
            log.warning("news.yf_news_failed", ticker=ticker, error=str(exc))
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _fetch_newsapi(
        self, ticker: str, company_name: str, limit: int
    ) -> list[NewsItem]:
        query = f"{company_name} OR {ticker} stock"
        params = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": limit,
            "language": "en",
            "apiKey": self._api_key,
        }
        resp = await self._client.get(_NEWSAPI_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

        items: list[NewsItem] = []
        for article in data.get("articles", []):
            published = _parse_dt(article.get("publishedAt"))
            items.append(
                NewsItem(
                    title=article.get("title", ""),
                    source=article.get("source", {}).get("name", "NewsAPI"),
                    published_at=published,
                    url=article.get("url"),
                    summary=article.get("description"),
                )
            )
        return items

    async def _fetch_google_news_rss(
        self, ticker: str, company_name: str, limit: int
    ) -> list[NewsItem]:
        """Parse Google News RSS — no API key needed."""
        query = quote_plus(f"{company_name} {ticker}")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return _parse_rss(resp.text, limit)
        except Exception as exc:
            log.error("news.google_rss_failed", ticker=ticker, error=str(exc))
            return []

    async def get_market_news(self, market: str, limit: int = 25) -> list[NewsItem]:
        """
        Fetch broad market / business news for the Radar feature.
        Uses NewsAPI top-headlines (if key available) + yfinance on a basket of
        index / ETF tickers to gather macro themes rather than single-stock news.
        """
        tasks: list = []
        if self._api_key:
            tasks.append(self._fetch_newsapi_headlines(market, min(limit, 20)))
        basket = _US_RADAR_BASKET if market == "us" else _IN_RADAR_BASKET
        tasks.append(self._fetch_basket_yf_news(basket, limit_per_ticker=3))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen: set[str] = set()
        merged: list[NewsItem] = []
        for batch in results:
            if isinstance(batch, Exception):
                log.warning("news.market_news_batch_failed", error=str(batch))
                continue
            for item in batch:
                key = item.title.lower()[:60]
                if key not in seen:
                    seen.add(key)
                    merged.append(item)

        merged.sort(
            key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        log.info("news.market_news_done", market=market, count=len(merged))
        return merged[:limit]

    async def _fetch_newsapi_headlines(self, market: str, limit: int) -> list[NewsItem]:
        country = "us" if market == "us" else "in"
        params = {
            "country": country,
            "category": "business",
            "pageSize": limit,
            "apiKey": self._api_key,
        }
        resp = await self._client.get(_NEWSAPI_HEADLINES, params=params)
        resp.raise_for_status()
        data = resp.json()
        items: list[NewsItem] = []
        for article in data.get("articles", []):
            published = _parse_dt(article.get("publishedAt"))
            title = article.get("title", "")
            if not title or title == "[Removed]":
                continue
            items.append(NewsItem(
                title=title,
                source=article.get("source", {}).get("name", "NewsAPI"),
                published_at=published,
                url=article.get("url"),
                summary=article.get("description"),
            ))
        return items

    async def _fetch_basket_yf_news(self, tickers: list[str], limit_per_ticker: int = 3) -> list[NewsItem]:
        """Fetch yfinance news for a basket of tickers in parallel."""
        tasks = [self._fetch_yf_news(ticker, limit_per_ticker) for ticker in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: list[NewsItem] = []
        for batch in results:
            if not isinstance(batch, Exception):
                items.extend(batch)
        return items

    async def close(self) -> None:
        await self._client.aclose()


def _parse_rss(xml: str, limit: int) -> list[NewsItem]:
    """Minimal RSS parser — avoids xml library dependency."""
    import re

    items: list[NewsItem] = []
    entries = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    for entry in entries[:limit]:
        title = _rss_tag(entry, "title")
        pub_date = _rss_tag(entry, "pubDate")
        source = _rss_tag(entry, "source")
        link = _rss_tag(entry, "link")
        items.append(
            NewsItem(
                title=title,
                source=source or "Google News",
                published_at=_parse_dt(pub_date),
                url=link or None,
            )
        )
    return items


def _rss_tag(text: str, tag: str) -> str:
    import re
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None
