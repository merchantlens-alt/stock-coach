"""
Shared Google Application Default Credentials (ADC) token cache.

Google OAuth 2.0 access tokens are valid for 60 minutes. Re-fetching a fresh
token on every Gemini call (analyst + predictor + market analyst = 3× per page
load) wastes 1-2 seconds each time. This module caches the token for 55 minutes
so the refresh only happens once per hour.

Thread-safety: uses a threading.Lock so concurrent async tasks sharing the same
process don't race on the refresh path.
"""
from __future__ import annotations

import time
from threading import Lock

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TTL = 3300  # 55 minutes (tokens valid for 60)

_lock = Lock()
_token: str | None = None
_expires_at: float = 0.0


def get_cached_token() -> str:
    """Return a valid bearer token, refreshing only when the cached one is near expiry."""
    global _token, _expires_at

    with _lock:
        if _token and time.time() < _expires_at:
            return _token

        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=[_SCOPE])
        creds.refresh(google.auth.transport.requests.Request())
        _token = creds.token  # type: ignore[assignment]
        _expires_at = time.time() + _TTL
        return _token


def clear_token_cache() -> None:
    """Force the next call to fetch a fresh token (useful in tests)."""
    global _token, _expires_at
    with _lock:
        _token = None
        _expires_at = 0.0
