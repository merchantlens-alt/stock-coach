"""User authentication utilities — password hashing and JWT management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, username: str, secret: str, expire_days: int) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=expire_days),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on any failure."""
    return jwt.decode(token, secret, algorithms=[_ALGORITHM])
