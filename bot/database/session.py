"""
Async SQLAlchemy engine and session factory.

`asyncpg` is used as the PostgreSQL driver (see DATABASE_URL in settings).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized")
    return _engine


def init_engine(database_url: str, *, echo: bool = False) -> async_sessionmaker[AsyncSession]:
    """
    Create a global async engine and session factory.

    Call once during application startup (see `bot.main`).
    """
    global _engine, _session_factory
    if _engine is not None:
        raise RuntimeError("Database engine already initialized")

    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        autoflush=False,
    )
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_engine() first")
    return _session_factory


async def dispose_engine() -> None:
    """Dispose connections on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session with commit/rollback semantics."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
