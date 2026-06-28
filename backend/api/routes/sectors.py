"""
Sector routes — GET /api/sectors/{market}

Returns all sectors ranked by sort_score with top 5 stocks per sector.
Cached 24 h; bypass with ?refresh=true.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_cache, get_current_user
from core.logging import get_logger
from models.schemas import SectorScanResponse, UserRecord
from services.cache import CacheBackend
from services.sector_service import get_sector_scan

router = APIRouter(prefix="/sectors", tags=["sectors"])
log = get_logger(__name__)


@router.get("/{market}", response_model=SectorScanResponse)
async def list_sectors(
    market: Literal["india", "us"],
    cache: Annotated[CacheBackend, Depends(get_cache)],
    current_user: Annotated[UserRecord, Depends(get_current_user)],
    refresh: Annotated[bool, Query()] = False,
) -> SectorScanResponse:
    """
    Return all sectors for the given market, ranked by sort_score (best first).
    Each sector contains top 5 stocks sorted by 1-year return.
    """
    if market not in ("india", "us"):
        raise HTTPException(status_code=422, detail="market must be 'india' or 'us'")

    log.info("sectors.list", market=market, user=current_user.username, refresh=refresh)
    return await get_sector_scan(market, cache, refresh=refresh)
