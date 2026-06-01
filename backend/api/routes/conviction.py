"""
Conviction / thesis analysis endpoints.

POST /api/conviction/analyse
  Body: { "belief": "I believe AI will drive memory demand", "market": "us" }
  Returns: ConvictionResponse — structured thesis with instruments, confirmers,
           entry signal, and exit triggers.

Cache key: conviction:{market}:{belief_hash}
TTL: 24 h (thesis data doesn't change minute to minute)
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from agents.thesis_analyst import ThesisAnalystAgent
from api.deps import get_cache, get_thesis_analyst
from core.exceptions import AIAgentError
from core.logging import get_logger
from models.schemas import ConvictionRequest, ConvictionResponse
from services.cache import CacheBackend

router = APIRouter(prefix="/conviction", tags=["conviction"])
log = get_logger(__name__)

_CONVICTION_TTL = 24 * 3600  # 24 h


def _conviction_cache_key(belief: str, market: str) -> str:
    """Stable cache key from (belief, market) — SHA-256 truncated to 16 chars."""
    digest = hashlib.sha256(f"{market}:{belief.lower().strip()}".encode()).hexdigest()[:16]
    return f"conviction:{market}:{digest}"


@router.post("/analyse", response_model=ConvictionResponse)
async def analyse_conviction(
    body: ConvictionRequest,
    cache: Annotated[CacheBackend, Depends(get_cache)],
    analyst: Annotated[ThesisAnalystAgent, Depends(get_thesis_analyst)],
) -> ConvictionResponse:
    """
    Analyse an investment belief and return a structured conviction thesis.

    Cached per (belief, market) for 24 h — repeated searches are instant.
    """
    key = _conviction_cache_key(body.belief, body.market)

    cached = await cache.get(key)
    if cached:
        log.info("conviction.cache_hit", market=body.market, belief_preview=body.belief[:60])
        from models.schemas import ThesisConviction
        return ConvictionResponse(
            conviction=ThesisConviction(**cached["conviction"]),
            from_cache=True,
            analysed_at=cached.get("analysed_at"),
        )

    log.info("conviction.analyse_start", market=body.market, belief_preview=body.belief[:60])

    try:
        conviction = await analyst.analyse(body.belief, body.market)
    except Exception as exc:
        # Catches AIAgentError, httpx.HTTPStatusError, timeouts, and any other failure.
        # Always fall back to mock so the user sees something rather than a 500.
        log.error("conviction.ai_failed", error=str(exc), error_type=type(exc).__name__)
        from core.config import get_settings
        from agents.thesis_analyst import ThesisAnalystAgent as _Agent
        settings = get_settings()
        mock_agent = _Agent(settings.model_copy(update={"mock_ai": True}))
        conviction = await mock_agent.analyse(body.belief, body.market)
        return ConvictionResponse(
            conviction=conviction,
            from_cache=False,
            analysed_at=datetime.utcnow(),
        )

    response = ConvictionResponse(
        conviction=conviction,
        from_cache=False,
        analysed_at=datetime.utcnow(),
    )

    await cache.set(key, {
        "conviction": conviction.model_dump(),
        "analysed_at": response.analysed_at.isoformat() if response.analysed_at else None,
    }, _CONVICTION_TTL)

    log.info("conviction.analyse_done", market=body.market, belief_preview=body.belief[:60])
    return response
