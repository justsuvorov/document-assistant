"""Async-движок SQLAlchemy.

DATABASE_URL по умолчанию — SQLite (локальная разработка), в compose
подставляется Postgres. Оба варианта асинхронные: aiosqlite / asyncpg.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from document_assistant.core.settings import settings
from document_assistant.db.models import Base

_engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)

async_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Создать таблицы, если их нет.

    Схема состоит из одной таблицы, поэтому Alembic пока избыточен. Когда
    появится вторая миграция — заменить на нормальные миграции.
    """
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await _engine.dispose()
