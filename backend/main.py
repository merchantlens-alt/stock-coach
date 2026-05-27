from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import gainers, health
from core.config import get_settings
from core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "stockcoach.startup",
        mock_ai=settings.mock_ai,
        redis=settings.use_redis,
        region=settings.google_cloud_region,
    )
    yield
    log.info("stockcoach.shutdown")


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
    app.include_router(gainers.router, prefix="/api")

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
