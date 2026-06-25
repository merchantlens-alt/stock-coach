from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import advisor, conviction, funds, gainers, growth_triggers, health, investor_profile, portfolio
from core.config import get_settings
from core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio
    settings = get_settings()
    log.info(
        "stockcoach.startup",
        mock_ai=settings.mock_ai,
        redis=settings.use_redis,
        region=settings.google_cloud_region,
    )
    # Pre-warm the gainers cache in background so the first user never waits.
    # Cloud Run keeps the container alive between requests, so this is free.
    if not settings.mock_ai:
        asyncio.create_task(_warm_gainers_cache())
    yield
    log.info("stockcoach.shutdown")


async def _warm_gainers_cache() -> None:
    """Fetch US and India gainers on startup so the 30-min cache is already hot."""
    import asyncio
    from api.deps import get_cache, get_market_data
    from core.config import get_settings as _get_settings
    from services.market_data import today_str

    try:
        _settings = _get_settings()
        cache = get_cache(_settings)
        market_data = get_market_data(_settings)

        async def _fetch_if_stale(market: str) -> None:
            key = f"gainers:{market}"   # matches _list_cache_key — no date suffix
            if await cache.get(key):
                log.info("startup.cache_already_warm", market=market)
                return
            log.info("startup.warming_cache", market=market)
            await market_data.get_gainers(market)  # type: ignore[arg-type]
            log.info("startup.cache_warmed", market=market)

        await asyncio.gather(
            _fetch_if_stale("us"),
            _fetch_if_stale("india"),
            return_exceptions=True,
        )
    except Exception as exc:
        log.warning("startup.cache_warm_failed", error=str(exc))


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="StockCoach AI",
        description="Top gainers analysis and AI-powered growth prediction for US and Indian stocks.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(investor_profile.router, prefix="/api")
    app.include_router(advisor.router, prefix="/api")
    app.include_router(gainers.router, prefix="/api")
    app.include_router(growth_triggers.router, prefix="/api")
    app.include_router(conviction.router, prefix="/api")
    app.include_router(portfolio.router, prefix="/api")
    app.include_router(funds.router, prefix="/api")

    # Serve React frontend — only if the built static directory exists (production)
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> FileResponse:
            index = static_dir / "index.html"
            return FileResponse(index)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
