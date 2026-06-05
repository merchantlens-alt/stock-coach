from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from agents.catalyst_analyst import CatalystAnalystAgent
from agents.gainer_analyst import GainerAnalystAgent
from agents.growth_triggers_agent import GrowthTriggersAgent
from agents.market_analyst import MarketAnalystAgent
from agents.radar_analyst import RadarAnalystAgent
from agents.thesis_analyst import ThesisAnalystAgent
from core.config import Settings, get_settings
from services.cache import CacheBackend, build_cache
from services.catalyst_scanner import CatalystScannerService
from services.fundamental_enricher import FundamentalEnricher
from services.market_data import MarketDataService
from services.news_fetcher import NewsFetcher
from services.dip_scanner import DipScannerService
from services.portfolio_store import PortfolioStore
from services.quarterly_fetcher import QuarterlyFetcher

# Module-level singletons — lru_cache cannot be used here because
# Pydantic v2 BaseSettings instances are not hashable.
_cache: CacheBackend | None = None
_market_data: MarketDataService | None = None
_news_fetcher: NewsFetcher | None = None
_gainer_analyst: GainerAnalystAgent | None = None
_market_analyst: MarketAnalystAgent | None = None
_thesis_analyst: ThesisAnalystAgent | None = None
_radar_analyst: RadarAnalystAgent | None = None
_quarterly_fetcher: QuarterlyFetcher | None = None
_catalyst_analyst: CatalystAnalystAgent | None = None
_catalyst_scanner: CatalystScannerService | None = None
_growth_triggers_agent: GrowthTriggersAgent | None = None
_portfolio_store: PortfolioStore | None = None
_dip_scanner: DipScannerService | None = None
_fundamental_enricher: FundamentalEnricher | None = None


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


def get_thesis_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ThesisAnalystAgent:
    global _thesis_analyst
    if _thesis_analyst is None:
        _thesis_analyst = ThesisAnalystAgent(settings)
    return _thesis_analyst


def get_radar_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RadarAnalystAgent:
    global _radar_analyst
    if _radar_analyst is None:
        _radar_analyst = RadarAnalystAgent(settings)
    return _radar_analyst


def get_quarterly_fetcher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> QuarterlyFetcher:
    global _quarterly_fetcher
    if _quarterly_fetcher is None:
        _quarterly_fetcher = QuarterlyFetcher(settings)
    return _quarterly_fetcher


def get_catalyst_analyst(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CatalystAnalystAgent:
    global _catalyst_analyst
    if _catalyst_analyst is None:
        _catalyst_analyst = CatalystAnalystAgent(settings)
    return _catalyst_analyst


def get_catalyst_scanner(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CatalystScannerService:
    global _catalyst_scanner
    if _catalyst_scanner is None:
        _catalyst_scanner = CatalystScannerService(
            settings,
            get_market_data(settings),
            get_news_fetcher(settings),
            get_catalyst_analyst(settings),
        )
    return _catalyst_scanner


def get_growth_triggers_agent(
    settings: Annotated[Settings, Depends(get_settings)],
) -> GrowthTriggersAgent:
    global _growth_triggers_agent
    if _growth_triggers_agent is None:
        _growth_triggers_agent = GrowthTriggersAgent(settings)
    return _growth_triggers_agent


def get_dip_scanner(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DipScannerService:
    global _dip_scanner
    if _dip_scanner is None:
        _dip_scanner = DipScannerService(settings)
    return _dip_scanner


def get_portfolio_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PortfolioStore:
    global _portfolio_store
    if _portfolio_store is None:
        _portfolio_store = PortfolioStore(get_cache(settings))
    return _portfolio_store


def get_fundamental_enricher() -> FundamentalEnricher:
    """
    FundamentalEnricher is stateless (no Settings needed).
    Returns the shared singleton so yfinance connection overhead is amortised.
    """
    global _fundamental_enricher
    if _fundamental_enricher is None:
        _fundamental_enricher = FundamentalEnricher()
    return _fundamental_enricher


