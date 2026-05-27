from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from agents.gainer_analyst import GainerAnalystAgent
from agents.predictor import PredictorAgent
from core.config import Settings, get_settings
from services.cache import CacheBackend, build_cache
from services.market_data import MarketDataService
from services.news_fetcher import NewsFetcher


@lru_cache
def _get_cache(settings: Settings) -> CacheBackend:
    return build_cache(settings.redis_url)


@lru_cache
def _get_market_data(settings: Settings) -> MarketDataService:
    return MarketDataService(settings)


@lru_cache
def _get_news_fetcher(settings: Settings) -> NewsFetcher:
    return NewsFetcher(settings)


@lru_cache
def _get_gainer_analyst(settings: Settings) -> GainerAnalystAgent:
    return GainerAnalystAgent(settings)


@lru_cache
def _get_predictor(settings: Settings) -> PredictorAgent:
    return PredictorAgent(settings)


# FastAPI dependency callables
def get_cache(settings: Annotated[Settings, Depends(get_settings)]) -> CacheBackend:
    return _get_cache(settings)


def get_market_data(settings: Annotated[Settings, Depends(get_settings)]) -> MarketDataService:
    return _get_market_data(settings)


def get_news_fetcher(settings: Annotated[Settings, Depends(get_settings)]) -> NewsFetcher:
    return _get_news_fetcher(settings)


def get_gainer_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GainerAnalystAgent:
    return _get_gainer_analyst(settings)


def get_predictor(settings: Annotated[Settings, Depends(get_settings)]) -> PredictorAgent:
    return _get_predictor(settings)
