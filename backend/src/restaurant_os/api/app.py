"""
FastAPI application factory.

"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import settings
from ..db.session import engine, init_db
from .v1.routes import router as api_v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage startup and shutdown events for the FastAPI app.

    On startup: initialise DB connection pool, warm any caches.
    On shutdown: close the DB pool gracefully.

    Replaces Django's AppConfig.ready() + signal handlers.
    """
    await init_db()
    # TODO: initialise Redis connection (Section 8)
    yield
    await engine.dispose()
    # TODO: close Redis connection


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application instance.

    - Attaches the lifespan context manager (startup/shutdown).
    - Adds CORS middleware (equivalent to django-cors-headers).
    - Mounts the v1 API router under /api/v1.

    Returns the configured FastAPI app ready to pass to uvicorn.
    """
    app = FastAPI(
        title="Restaurant OS",
        version="0.1.0",
        lifespan=lifespan,
    )

    allowed_origins = settings.cors_allowed_origins.split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router)

    return app


# Module-level app instance consumed by uvicorn:
#   uvicorn src.restaurant_os.api.app:app --reload
app = create_app()
