from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from agents.gainer_analyst import GainerAnalystAgent
from agents.market_analyst import MarketAnalystAgent
from core.config import Settings, get_settings
from services.cache import CacheBackend, build_cache
from services.market_data import MarketDataService
from services.news_fetcher import NewsFetcher

# Module-level singletons — lru_cache cannot be used here because
# Pydantic v2 BaseSettings instances are not hashable.
_cache: CacheBackend | None = None
_market_data: MarketDataService | None = None
_news_fetcher: NewsFetcher | None = None
_gainer_analyst: GainerAnalystAgent | None = None
_market_analyst: MarketAnalystAgent | None = None


def get_cache(settings: Annotated[Settings, Depends(get_settings)]) -> CacheBackend:
    global _cache
    if _cache is None:
        _cache = build_cache(settings.redis_url)
    return _cache


def get_market_data(settings: Annotated[Settings, Depends(get_settings)]) -> MarketDataService:
    global _market_data
    if _market_data is None:
        _market_data = MarketDataService(settings)
    return _market_data


def get_news_fetcher(settings: Annotated[Settings, Depends(get_settings)]) -> NewsFetcher:
    global _news_fetcher
    if _news_fetcher is None:
        _news_fetcher = NewsFetcher(settings)
    return _news_fetcher


def get_gainer_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GainerAnalystAgent:
    global _gainer_analyst
    if _gainer_analyst is None:
        _gainer_analyst = GainerAnalystAgent(settings)
    return _gainer_analyst


def get_market_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketAnalystAgent:
    global _market_analyst
    if _market_analyst is None:
        _market_analyst = MarketAnalystAgent(settings)
    return _market_analyst


