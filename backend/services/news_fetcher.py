from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import Settings
from core.exceptions import NewsError
from core.logging import get_logger
from models.schemas import NewsItem

log = get_logger(__name__)

_NEWSAPI_BASE = "https://newsapi.org/v2/everything"
_GNEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


class NewsFetcher:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.news_api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_news(self, ticker: str, company_name: str, limit: int = 8) -> list[NewsItem]:
        """
        Fetch recent news for a ticker. Falls back to Google News RSS
        if NewsAPI key is not configured or the request fails.
        """
        if self._api_key:
            try:
                return await self._fetch_newsapi(ticker, company_name, limit)
            except Exception as exc:
                log.warning("news.newsapi_failed", ticker=ticker, error=str(exc))

        return await self._fetch_google_news_rss(ticker, company_name, limit)

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
