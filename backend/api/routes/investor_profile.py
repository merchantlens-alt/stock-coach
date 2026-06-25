"""Investor Profile routes — GET / PUT /api/investor-profile"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user, get_investor_profile_store
from core.logging import get_logger
from models.schemas import InvestorProfile, UserRecord
from services.investor_profile_store import InvestorProfileStore

router = APIRouter(prefix="/investor-profile", tags=["advisor"])
log = get_logger(__name__)


@router.get("", response_model=InvestorProfile)
async def get_profile(
    store: Annotated[InvestorProfileStore, Depends(get_investor_profile_store)],
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> InvestorProfile:
    profile = await store.get(current_user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No investor profile set yet.")
    return profile


@router.put("", response_model=InvestorProfile)
async def save_profile(
    body: InvestorProfile,
    store: Annotated[InvestorProfileStore, Depends(get_investor_profile_store)],
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> InvestorProfile:
    await store.save(body, current_user.user_id)
    log.info("investor_profile.saved", horizon_years=body.horizon_years, user=current_user.username)
    return body
