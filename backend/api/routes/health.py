from typing import Annotated

from fastapi import APIRouter, Depends

from api.deps import get_cache
from core.config import Settings, get_settings
from models.schemas import HealthResponse
from services.cache import CacheBackend, InMemoryCache

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
    cache: Annotated[CacheBackend, Depends(get_cache)],
) -> HealthResponse:
    cache_healthy = await cache.ping()
    return HealthResponse(
        status="ok" if cache_healthy else "degraded",
        version="1.0.0",
        cache="redis" if not isinstance(cache, InMemoryCache) else "memory",
        ai="mock" if settings.mock_ai else "vertex_ai",
    )
