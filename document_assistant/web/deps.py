"""Общие зависимости веб-слоя."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from document_assistant.db.engine import async_session_factory

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
