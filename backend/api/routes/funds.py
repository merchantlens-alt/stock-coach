"""
Fund Scanner route — GET /api/funds/scan

Scans a curated universe of India mutual funds (Direct-Growth plans) via mfapi.in,
computes NAV-derived metrics, and returns an AI/heuristic "should I enter now"
verdict per fund.

Optional `?category=` narrows to one category (Flexi Cap, Large Cap, Small Cap,
Mid Cap, ELSS, Index, Contra, Value). `?refresh=true` busts the cache.

Cache TTL: 6 hours — mutual-fund NAVs publish once daily after market close.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends

from api.deps import get_cache, get_fund_data
from core.logging import get_logger
from models.schemas import FundScanResponse, ModelPortfolioResponse, RiskProfile
from services.cache import CacheBackend
from services.fund_data import FundDataService

router = APIRouter(prefix="/funds", tags=["funds"])
log = get_logger(__name__)

_FUNDS_TTL = 6 * 60 * 60  # 6 hours

_VALID_RISK = {"conservative", "balanced", "aggressive"}


def _cache_key(category: Optional[str]) -> str:
    return f"funds:scan:{(category or 'all').lower()}"


@router.get("/scan", response_model=FundScanResponse)
async def scan_funds(
    cache: Annotated[CacheBackend, Depends(get_cache)],
    funds: Annotated[FundDataService, Depends(get_fund_data)],
    category: Optional[str] = None,
    refresh: bool = False,
) -> FundScanResponse:
    """
    Returns scored India mutual funds with an entry verdict (strong_entry / watch /
    avoid) and plain-English reasoning grounded in NAV-derived metrics:
    rolling returns, 3y/5y CAGR, Sharpe ratio, and max drawdown.

    Cached 6 hours per category. Pass `?refresh=true` to force a fresh scan.
    """
    key = _cache_key(category)

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("funds.cache_hit", category=category or "all")
            return FundScanResponse(**{**cached, "from_cache": True})
    else:
        log.info("funds.cache_bust", category=category or "all")

    log.info("funds.cold_scan_start", category=category or "all")
    response = await funds.scan(category=category)
    response.scanned_at = datetime.utcnow()

    if response.funds:
        await cache.set(key, response.model_dump(mode="json"), _FUNDS_TTL)
        log.info("funds.cached", category=category or "all", count=len(response.funds), ttl=_FUNDS_TTL)

    return response


@router.get("/model-portfolio", response_model=ModelPortfolioResponse)
async def model_portfolio(
    cache: Annotated[CacheBackend, Depends(get_cache)],
    funds: Annotated[FundDataService, Depends(get_fund_data)],
    risk: RiskProfile = "balanced",
    refresh: bool = False,
) -> ModelPortfolioResponse:
    """
    A generic 5-fund model portfolio — "the funds you should own" — for a self-
    selected risk level (conservative / balanced / aggressive). One fund per role
    (Core / Anchor / Growth / High-Growth / Satellite), each the best long-term
    pick in its category with rule-outs excluded and AMC overlap avoided.

    No personal profiling — the risk flavour is self-selected. Cached 6 hours.
    """
    risk_key = risk if risk in _VALID_RISK else "balanced"
    key = f"funds:model:{risk_key}"

    if not refresh:
        cached = await cache.get(key)
        if cached:
            log.info("funds.model_cache_hit", risk=risk_key)
            return ModelPortfolioResponse(**{**cached, "from_cache": True})

    log.info("funds.model_build", risk=risk_key)
    response = await funds.build_model_portfolio(risk=risk_key)
    response.generated_at = datetime.utcnow()

    if response.holdings:
        await cache.set(key, response.model_dump(mode="json"), _FUNDS_TTL)

    return response
