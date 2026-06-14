"""
Fund routes — GET /api/funds/scan and /api/funds/model-portfolio

`market=india` (default) scans India mutual funds (Direct-Growth, via mfapi.in,
NAV-derived metrics, category-relative scoring with saturation/closet rule-outs).
`market=us` scans a curated universe of US ETFs (via yfinance, cost-led scoring
with real expense ratio + AUM).

`?category=` narrows to one category, `?refresh=true` busts the cache.
Cache TTL: 6 hours.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_fund_data, get_us_etf_data
from core.logging import get_logger
from models.schemas import (
    CompareRequest,
    CompareResponse,
    FundScanResponse,
    Market,
    ModelPortfolioResponse,
    RiskProfile,
)
from services.cache import CacheBackend
from services.fund_compare import run_compare
from services.fund_data import FundDataService
from services.us_etf_data import USETFDataService

router = APIRouter(prefix="/funds", tags=["funds"])
log = get_logger(__name__)

_FUNDS_TTL = 6 * 60 * 60  # 6 hours

_VALID_RISK = {"conservative", "balanced", "aggressive"}


def _scan_key(market: str, category: Optional[str]) -> str:
    return f"funds:scan:{market}:{(category or 'all').lower()}"


@router.get("/scan", response_model=FundScanResponse)
async def scan_funds(
    cache: Annotated[CacheBackend, Depends(get_cache)],
    india: Annotated[FundDataService, Depends(get_fund_data)],
    us: Annotated[USETFDataService, Depends(get_us_etf_data)],
    market: Market = "india",
    category: Optional[str] = None,
    refresh: bool = False,
) -> FundScanResponse:
    """
    Returns scored funds with an entry verdict and plain-English reasoning.

    India (default): mutual funds ranked category-relative on alpha, Sharpe, and
    drawdown, with saturated and closet-index funds ruled out.
    US: ETFs ranked cost-led on expense ratio, long-term return, Sharpe, and size.

    Cached 6 hours per market+category. Pass `?refresh=true` to force a fresh scan.
    """
    key = _scan_key(market, category)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("funds.cache_hit", market=market, category=category or "all")
            return FundScanResponse(**{**cached, "from_cache": True})
    else:
        log.info("funds.cache_bust", market=market, category=category or "all")

    log.info("funds.cold_scan_start", market=market, category=category or "all")
    service = us if market == "us" else india
    response = await service.scan(category=category)
    response.scanned_at = datetime.utcnow()

    if response.funds:
        await cache.set(key, response.model_dump(mode="json"), _FUNDS_TTL)
        log.info("funds.cached", market=market, category=category or "all", count=len(response.funds))

    return response


@router.get("/model-portfolio", response_model=ModelPortfolioResponse)
async def model_portfolio(
    cache: Annotated[CacheBackend, Depends(get_cache)],
    india: Annotated[FundDataService, Depends(get_fund_data)],
    us: Annotated[USETFDataService, Depends(get_us_etf_data)],
    market: Market = "india",
    risk: RiskProfile = "balanced",
    refresh: bool = False,
) -> ModelPortfolioResponse:
    """
    A generic 5-fund model portfolio — "the funds you should own" — for a self-
    selected risk level. India: active funds across market caps. US: a Boglehead-
    style lazy ETF allocation (broad core + growth tilt + international + income +
    diversifier). No personal profiling. Cached 6 hours.
    """
    risk_key = risk if risk in _VALID_RISK else "balanced"
    key = f"funds:model:{market}:{risk_key}"

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("funds.model_cache_hit", market=market, risk=risk_key)
            return ModelPortfolioResponse(**{**cached, "from_cache": True})

    log.info("funds.model_build", market=market, risk=risk_key)
    service = us if market == "us" else india
    response = await service.build_model_portfolio(risk=risk_key)
    response.generated_at = datetime.utcnow()

    if response.holdings:
        await cache.set(key, response.model_dump(mode="json"), _FUNDS_TTL)

    return response


@router.post("/compare", response_model=CompareResponse)
async def compare_funds(
    body: CompareRequest,
    india: Annotated[FundDataService, Depends(get_fund_data)],
    us: Annotated[USETFDataService, Depends(get_us_etf_data)],
) -> CompareResponse:
    """
    Backtest a lumpsum: "if I'd invested `amount` across MY funds N years ago vs
    the model portfolio, where would I be today?" Trailing 1 / 3 / 5 years.

    Funds without enough history for a window are dropped and weights renormalised
    (coverage is reported per window). Not cached — inputs vary per request.
    """
    service = us if body.market == "us" else india
    response = await run_compare(service, body)
    response.generated_at = datetime.utcnow()
    return response
