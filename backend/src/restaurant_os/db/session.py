"""
Async SQLAlchemy session factory and FastAPI dependency.

"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..core.config import settings
from .models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine — created once at module import; shared across all requests.
#
# pool_pre_ping=True re-validates connections before use, recovering from
# DB restarts without raising stale-connection errors at request time.
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# ---------------------------------------------------------------------------
# Session factory — produces AsyncSession objects for each database operation.
#
# expire_on_commit=False prevents SQLAlchemy from expiring ORM attributes after
# commit, which would trigger lazy-load errors in async code (there is no
# implicit I/O in async SQLAlchemy).
# ---------------------------------------------------------------------------

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables from ORM model metadata.

    Safe to call on startup in development. For production deployments use
    Alembic migrations (alembic upgrade head) instead of create_all to avoid
    destructive schema drift on existing data.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db.session: schema initialised via create_all")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields one AsyncSession per HTTP request.

    Commits automatically on clean exit; rolls back on any exception so the
    database is never left in a partial state. The session is closed by the
    async context manager when the generator is exhausted.

    Usage in a route handler:
        from sqlalchemy.ext.asyncio import AsyncSession
        from fastapi import Depends
        from restaurant_os.db.session import get_session

        async def my_route(session: AsyncSession = Depends(get_session)):
            repo = SupplierRepository(session)
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
