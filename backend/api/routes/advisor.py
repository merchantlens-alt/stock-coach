"""
Advisor routes — GET /api/advisor/allocation-plan, POST /api/advisor/evaluate

Cache keys are scoped per user so one user's data never leaks to another.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from agents.advisor_agent import AdvisorAgent
from agents.allocation_advisor_agent import AllocationAdvisorAgent
from api.deps import (
    get_advisor_agent, get_allocation_advisor, get_cache,
    get_current_user, get_investor_profile_store, get_market_data,
)
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import (
    AdvisorEvaluateRequest,
    AdvisorEvaluateResponse,
    AdvisorRecommendation,
    AllocationPlanResponse,
    UserRecord,
)
from services.cache import CacheBackend
from services.investor_profile_store import InvestorProfileStore
from services.market_data import MarketDataService

router = APIRouter(prefix="/advisor", tags=["advisor"])
log = get_logger(__name__)

_ADVISOR_TTL = 6 * 3600   # 6 h
_PLAN_TTL    = 24 * 3600  # 24 h


def _profile_hash(profile_dict: dict) -> str:
    blob = json.dumps(profile_dict, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _filter_candidates(gainers: list, max_n: int = 15) -> list[dict]:
    """Keep quality-scored stocks; prefer confirmed/catalyst tiers."""
    scored = [
        g for g in gainers
        if g.signal_tier in ("confirmed", "catalyst") or (g.quality_score or 0) >= 50
    ]
    scored.sort(key=lambda g: (-(g.quality_score or 0)))
    return [
        {
            "ticker": g.ticker,
            "name": g.name,
            "sector": g.sector or "Unknown",
            "quality_score": round(g.quality_score or 0, 1),
            "signal_tier": g.signal_tier,
            "change_pct": round(g.change_pct, 2),
        }
        for g in scored[:max_n]
    ]


@router.get("/allocation-plan", response_model=AllocationPlanResponse)
async def get_allocation_plan(
    store: Annotated[InvestorProfileStore, Depends(get_investor_profile_store)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    agent: Annotated[AllocationAdvisorAgent, Depends(get_allocation_advisor)],
    market_data: Annotated[MarketDataService, Depends(get_market_data)],
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> AllocationPlanResponse:
    profile = await store.get(current_user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No investor profile set. Create your profile first.")
    if not profile.monthly_invest_amount:
        raise HTTPException(status_code=422, detail="Monthly investable amount is required for the allocation plan.")

    ph = _profile_hash(profile.model_dump())
    key = f"user:{current_user.user_id}:allocation-plan:{ph}"

    cached = await cache.get(key)
    if cached:
        log.info("advisor.allocation_plan.cache_hit", user=current_user.username)
        plan = AllocationPlanResponse.model_validate(cached)
        plan.from_cache = True
        return plan

    # Fetch live stock candidates for both markets in parallel; never block the plan on failure
    import asyncio
    india_raw, us_raw = await asyncio.gather(
        market_data.get_gainers("india"),
        market_data.get_gainers("us"),
        return_exceptions=True,
    )
    india_candidates = _filter_candidates(india_raw) if not isinstance(india_raw, Exception) else []
    us_candidates = _filter_candidates(us_raw) if not isinstance(us_raw, Exception) else []
    if isinstance(india_raw, Exception):
        log.warning("advisor.allocation_plan.india_candidates_failed", error=str(india_raw))
    if isinstance(us_raw, Exception):
        log.warning("advisor.allocation_plan.us_candidates_failed", error=str(us_raw))

    log.info(
        "advisor.allocation_plan.generate",
        user=current_user.username,
        india_candidates=len(india_candidates),
        us_candidates=len(us_candidates),
    )
    try:
        plan = await agent.create_plan(profile, india_candidates=india_candidates, us_candidates=us_candidates)
    except AIAgentError as exc:
        log.error("advisor.allocation_plan.ai_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Allocation plan AI unavailable. Try again shortly.")

    plan.generated_at = datetime.utcnow()
    await cache.set(key, plan.model_dump(mode="json"), _PLAN_TTL)
    return plan


@router.post("/evaluate", response_model=AdvisorEvaluateResponse)
async def evaluate(
    body: AdvisorEvaluateRequest,
    store: Annotated[InvestorProfileStore, Depends(get_investor_profile_store)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    agent: Annotated[AdvisorAgent, Depends(get_advisor_agent)],
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> AdvisorEvaluateResponse:
    profile = await store.get(current_user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No investor profile set. Create your profile first.")

    ph = _profile_hash(profile.model_dump())
    key = f"user:{current_user.user_id}:advisor:{ph}:{body.asset_type}:{body.market}:{body.ticker.upper()}"

    cached = await cache.get(key)
    if cached:
        log.info("advisor.cache_hit", ticker=body.ticker, user=current_user.username)
        return AdvisorEvaluateResponse(
            recommendation=AdvisorRecommendation(**cached["recommendation"]),
            ticker=body.ticker,
            asset_type=body.asset_type,
            profile_horizon_years=profile.horizon_years,
            from_cache=True,
            evaluated_at=cached.get("evaluated_at"),
        )

    log.info("advisor.evaluate", ticker=body.ticker, user=current_user.username)
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
