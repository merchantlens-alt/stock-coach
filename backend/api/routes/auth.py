"""
Auth routes — POST /api/auth/register, POST /api/auth/login

Username + bcrypt password, JWT token returned on success.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_settings, get_user_store
from core.config import Settings
from core.logging import get_logger
from core.user_auth import create_access_token, hash_password, verify_password
from models.schemas import TokenResponse, UserCreate, UserLogin
from services.user_store import UserStore

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: UserCreate,
    store: Annotated[UserStore, Depends(get_user_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    if await store.exists(body.username):
        raise HTTPException(status_code=409, detail="Username already taken.")

    hashed = hash_password(body.password)
    record = await store.create(body.username, hashed)
    token = create_access_token(
        record["user_id"], record["username"],
        settings.jwt_secret, settings.jwt_expire_days,
    )
    log.info("auth.register", username=body.username)
    return TokenResponse(
        access_token=token,
        user_id=record["user_id"],
        username=record["username"],
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLogin,
    store: Annotated[UserStore, Depends(get_user_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    record = await store.get_by_username(body.username)
    if not record or not verify_password(body.password, record["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = create_access_token(
        record["user_id"], record["username"],
        settings.jwt_secret, settings.jwt_expire_days,
    )
    log.info("auth.login", username=body.username)
    return TokenResponse(
        access_token=token,
        user_id=record["user_id"],
        username=record["username"],
    )
