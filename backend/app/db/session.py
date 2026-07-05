"""Async database engine and session management.

The engine uses NullPool: connections are opened per session and closed on
release. asyncpg connections are bound to the event loop that created them,
and this process runs coroutines on more than one loop (FastAPI's main loop,
the TestClient portal loops in the test suite), so a shared connection pool
would hand loop-bound connections to the wrong loop. Per-request connects to
a local Postgres are cheap; put PgBouncer in front if this ever matters.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(settings.postgres_url, poolclass=NullPool)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async database session."""
    async with SessionLocal() as session:
        yield session
