"""Async-движок SQLAlchemy.

DATABASE_URL по умолчанию — SQLite (локальная разработка), в compose
подставляется Postgres. Оба варианта асинхронные: aiosqlite / asyncpg.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from document_assistant.core.settings import settings
from document_assistant.db.models import Base

_engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)

async_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Создать таблицы, если их нет, и дотянуть схему до актуальной.

    ``create_all`` создаёт только отсутствующие таблицы и НЕ добавляет колонки
    в существующие — при обновлении приложения над живой базой этого мало.
    Поэтому колонки очереди досоздаются отдельно и идемпотентно.

    Это последняя ручная миграция: следующее изменение схемы стоит делать
    уже через Alembic.
    """
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_queue_columns(conn)


async def _ensure_queue_columns(conn) -> None:
    """Добавить locked_at/attempts в таблицу, созданную прошлой версией."""
    dialect = conn.dialect.name
    if dialect == "postgresql":
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0"
        ))
    elif dialect == "sqlite":
        # SQLite не знает ADD COLUMN IF NOT EXISTS — смотрим состав таблицы.
        rows = await conn.execute(text("PRAGMA table_info(sessions)"))
        existing = {r[1] for r in rows}
        if "locked_at" not in existing:
            await conn.execute(text("ALTER TABLE sessions ADD COLUMN locked_at TIMESTAMP"))
        if "attempts" not in existing:
            await conn.execute(text(
                "ALTER TABLE sessions ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            ))


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await _engine.dispose()
