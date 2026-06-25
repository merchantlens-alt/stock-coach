"""
Advisor route — POST /api/advisor/evaluate

Intersects the investor's Bucket-1 profile with an asset's Bucket-2 metrics and
produces a personalised Buy / Pass / Conditional recommendation.

Cache key: advisor:{profile_hash}:{asset_type}:{market}:{ticker}
TTL: 6 h — profile changes naturally rotate the hash, so no manual invalidation needed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agents.advisor_agent import AdvisorAgent
from api.deps import get_advisor_agent, get_cache, get_investor_profile_store
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import AdvisorEvaluateRequest, AdvisorEvaluateResponse, AdvisorRecommendation
from services.cache import CacheBackend
from services.investor_profile_store import InvestorProfileStore

router = APIRouter(prefix="/advisor", tags=["advisor"])
log = get_logger(__name__)

_ADVISOR_TTL = 6 * 3600  # 6 h


def _cache_key(profile_hash: str, asset_type: str, market: str, ticker: str) -> str:
    return f"advisor:{profile_hash}:{asset_type}:{market}:{ticker.upper()}"


def _profile_hash(profile_dict: dict) -> str:
    """16-char stable hash of the profile — rotates cache when profile changes."""
    blob = json.dumps(profile_dict, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


@router.post("/evaluate", response_model=AdvisorEvaluateResponse)
async def evaluate(
    body: AdvisorEvaluateRequest,
    store: Annotated[InvestorProfileStore, Depends(get_investor_profile_store)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    agent: Annotated[AdvisorAgent, Depends(get_advisor_agent)],
) -> AdvisorEvaluateResponse:
    profile = await store.get()
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No investor profile set. Create your profile first.",
        )

    ph = _profile_hash(profile.model_dump())
    key = _cache_key(ph, body.asset_type, body.market, body.ticker)

    cached = await cache.get(key)
    if cached:
        log.info("advisor.cache_hit", ticker=body.ticker, asset_type=body.asset_type)
        return AdvisorEvaluateResponse(
            recommendation=AdvisorRecommendation(**cached["recommendation"]),
            ticker=body.ticker,
            asset_type=body.asset_type,
            profile_horizon_years=profile.horizon_years,
            from_cache=True,
            evaluated_at=cached.get("evaluated_at"),
        )

    log.info("advisor.evaluate", ticker=body.ticker, asset_type=body.asset_type)
    try:
        recommendation = await agent.evaluate(
            profile=profile,
            asset_type=body.asset_type,
            ticker=body.ticker,
            name=body.name,
            context=body.context,
        )
    except AIAgentError as exc:
        log.error("advisor.ai_failed", ticker=body.ticker, error=str(exc))
        raise HTTPException(status_code=503, detail="Advisor AI unavailable. Try again shortly.")

    now = datetime.utcnow().isoformat()
    result = AdvisorEvaluateResponse(
        recommendation=recommendation,
        ticker=body.ticker,
        asset_type=body.asset_type,
        profile_horizon_years=profile.horizon_years,
        from_cache=False,
        evaluated_at=datetime.utcnow(),
    )
    await cache.set(
        key,
        {"recommendation": recommendation.model_dump(), "evaluated_at": now},
        _ADVISOR_TTL,
    )
    return result
