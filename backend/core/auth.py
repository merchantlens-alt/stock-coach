"""
Shared Google Application Default Credentials (ADC) token cache.

Google OAuth 2.0 access tokens are valid for 60 minutes. Re-fetching a fresh
token on every Gemini call wastes 1-2 seconds each time. This module caches
the token and refreshes proactively before expiry.

Concurrency design
──────────────────
The original implementation used a threading.Lock inside asyncio.to_thread.
When the token expired during a burst of requests, all thread-pool threads
blocked on the lock waiting to refresh, exhausting the thread pool and making
the event loop unresponsive ("AI stops responding" symptom).

Fix: use an asyncio.Lock so waiting coroutines yield back to the event loop
instead of blocking OS threads. Only one coroutine ever calls the blocking
refresh; all others simply await the lock and get the cached token.
"""
from __future__ import annotations

import asyncio
import time

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TTL = 3000  # 50 minutes — extra buffer; tokens valid for 60

_lock: asyncio.Lock | None = None   # created lazily inside the running event loop
_token: str | None = None
_expires_at: float = 0.0


def _get_lock() -> asyncio.Lock:
    """Return the module-level asyncio.Lock, creating it inside the running loop."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _fetch_token_sync() -> str:
    """Blocking call — always runs inside asyncio.to_thread (a thread-pool thread)."""
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=[_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token  # type: ignore[return-value]


async def get_token() -> str:
    """
    Return a valid bearer token, refreshing only when the cached one is near expiry.

    Uses an asyncio.Lock so concurrent coroutines yield (non-blocking) while one
    does the actual refresh — avoids thread-pool starvation under burst load.
    """
    global _token, _expires_at

    async with _get_lock():
        # Re-check inside the lock — another coroutine may have refreshed already.
        if _token and time.time() < _expires_at:
            return _token

        new_token = await asyncio.to_thread(_fetch_token_sync)
        _token = new_token
        _expires_at = time.time() + _TTL
        return _token


# ── Sync shim for the rare case where blocking context is acceptable ──────────
def get_cached_token() -> str:
    """
    Blocking shim kept for backwards compatibility.

    Prefer get_token() (async) from within async code.
    Only use this where you're already in a thread (e.g. asyncio.to_thread caller).
    """
    global _token, _expires_at

    if _token and time.time() < _expires_at:
        return _token

    new_token = _fetch_token_sync()
    _token = new_token
    _expires_at = time.time() + _TTL
    return new_token


def clear_token_cache() -> None:
    """Force the next call to fetch a fresh token (useful in tests)."""
    global _token, _expires_at, _lock
    _token = None
    _expires_at = 0.0
    _lock = None
