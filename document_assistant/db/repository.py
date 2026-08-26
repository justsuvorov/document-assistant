"""Доступ к таблице sessions.

Ключевое правило: всё, что вызывается из HTTP-слоя, обязано фильтровать по
``user_id``. Методы без такой фильтрации доступны только воркеру и названы с
префиксом ``system_`` — так их легко найти на ревью и невозможно случайно
дёрнуть из роутера.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from document_assistant.db.models import ProcessingSession, SessionStatus, SessionType


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Пользовательские операции (всегда с проверкой владельца) ────────────

    async def create(
        self,
        user_id: str,
        input_keys: dict[str, str],
        user_name: str | None = None,
        session_type: SessionType = SessionType.DMS,
        max_chunks: int = 0,
    ) -> ProcessingSession:
        session = ProcessingSession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            user_name=user_name,
            session_type=session_type,
            status=SessionStatus.QUEUED,
            input_keys=input_keys,
            artifact_keys={},
            max_chunks=max_chunks,
        )
        self._db.add(session)
        await self._db.commit()
        await self._db.refresh(session)
        return session

    async def get_for_user(self, session_id: str, user_id: str) -> ProcessingSession | None:
        """Вернуть сессию, только если она принадлежит пользователю.

        Чужой session_id даёт None — вызывающий отвечает 404. Отдельного «есть,
        но чужая» не различаем намеренно: так не утекает факт существования.
        """
        stmt = select(ProcessingSession).where(
            ProcessingSession.id == session_id,
            ProcessingSession.user_id == user_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[ProcessingSession]:
        stmt = (
            select(ProcessingSession)
            .where(ProcessingSession.user_id == user_id)
            .order_by(ProcessingSession.created_at.desc())
            .limit(limit)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    # ── Операции воркера (владелец уже проверен при создании) ───────────────

    async def system_get(self, session_id: str) -> ProcessingSession | None:
        stmt = select(ProcessingSession).where(ProcessingSession.id == session_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def system_mark_processing(self, session_id: str, chunk_count: int | None = None) -> None:
        session = await self.system_get(session_id)
        if session is None:
            return
        session.status = SessionStatus.PROCESSING
        if chunk_count is not None:
            session.chunk_count = chunk_count
        await self._db.commit()

    async def system_mark_done(
        self, session_id: str, output_key: str, artifact_keys: dict[str, str]
    ) -> None:
        session = await self.system_get(session_id)
        if session is None:
            return
        session.status = SessionStatus.DONE
        session.output_key = output_key
        session.artifact_keys = artifact_keys
        session.error_message = None
        await self._db.commit()

    async def system_mark_error(self, session_id: str, message: str) -> None:
        session = await self.system_get(session_id)
        if session is None:
            return
        session.status = SessionStatus.ERROR
        # Сообщение уходит в UI — обрезаем, чтобы страница не разъезжалась.
        session.error_message = message[:2000]
        await self._db.commit()
