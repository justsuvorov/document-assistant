"""Доступ к таблице sessions.

Ключевое правило: всё, что вызывается из HTTP-слоя, обязано фильтровать по
``user_id``. Методы без такой фильтрации доступны только воркеру и названы с
префиксом ``system_`` — так их легко найти на ревью и невозможно случайно
дёрнуть из роутера.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from document_assistant.db.models import (
    ProcessingSession,
    SessionStatus,
    SessionType,
    _utcnow,
)


def _abandoned(threshold):
    """Условие «задача брошена»: захвачена давно либо вовсе без отметки."""
    return or_(
        ProcessingSession.locked_at < threshold,
        ProcessingSession.locked_at.is_(None),
    )


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
        session.locked_at = None
        session.output_key = output_key
        session.artifact_keys = artifact_keys
        session.error_message = None
        await self._db.commit()

    async def system_mark_error(self, session_id: str, message: str) -> None:
        session = await self.system_get(session_id)
        if session is None:
            return
        session.status = SessionStatus.ERROR
        session.locked_at = None
        # Сообщение уходит в UI — обрезаем, чтобы страница не разъезжалась.
        session.error_message = message[:2000]
        await self._db.commit()

    # ── Очередь: захват и возврат задач ─────────────────────────────────────

    async def system_claim_next(self) -> ProcessingSession | None:
        """Атомарно взять одну задачу из очереди и пометить processing.

        Захват — единственный UPDATE, а не «прочитать, потом записать»:
        иначе два воркера успели бы прочитать одну и ту же строку и обработали
        бы документ дважды. ``FOR UPDATE SKIP LOCKED`` заставляет второй воркер
        пропустить занятую строку, а не ждать её.

        SQLite не поддерживает SKIP LOCKED, но пишет в один поток и с одним
        воркером на файл, поэтому там достаточно обычного подзапроса.
        """
        skip_locked = self._db.get_bind().dialect.name == "postgresql"
        subq = (
            select(ProcessingSession.id)
            .where(ProcessingSession.status == SessionStatus.QUEUED)
            .order_by(ProcessingSession.created_at)
            .limit(1)
        )
        if skip_locked:
            subq = subq.with_for_update(skip_locked=True)

        stmt = (
            update(ProcessingSession)
            .where(ProcessingSession.id == subq.scalar_subquery())
            .values(
                status=SessionStatus.PROCESSING,
                locked_at=_utcnow(),
                attempts=ProcessingSession.attempts + 1,
            )
            .returning(ProcessingSession.id)
        )
        claimed_id = (await self._db.execute(stmt)).scalar_one_or_none()
        await self._db.commit()
        if claimed_id is None:
            return None
        return await self.system_get(claimed_id)

    async def system_requeue_stale(self, stale_after: int, max_attempts: int) -> int:
        """Вернуть в очередь задачи, брошенные упавшим воркером.

        Строка в processing без живого воркера иначе висела бы вечно: снаружи
        она выглядит как «обрабатывается», хотя обрабатывать её некому.
        Исчерпавшие попытки уходят в error, чтобы не крутиться по кругу.

        ``locked_at IS NULL`` тоже считается брошенной задачей: захват всегда
        проставляет отметку времени, поэтому её отсутствие означает строку от
        прошлой версии приложения — иначе такая задача не подметалась бы
        никогда (сравнение с NULL всегда ложно).
        """
        threshold = _utcnow() - timedelta(seconds=stale_after)

        exhausted = (
            update(ProcessingSession)
            .where(
                ProcessingSession.status == SessionStatus.PROCESSING,
                _abandoned(threshold),
                ProcessingSession.attempts >= max_attempts,
            )
            .values(
                status=SessionStatus.ERROR,
                error_message="Обработка прервана: превышено число попыток",
                locked_at=None,
            )
        )
        await self._db.execute(exhausted)

        retry = (
            update(ProcessingSession)
            .where(
                ProcessingSession.status == SessionStatus.PROCESSING,
                _abandoned(threshold),
                ProcessingSession.attempts < max_attempts,
            )
            .values(status=SessionStatus.QUEUED, locked_at=None)
        )
        result = await self._db.execute(retry)
        await self._db.commit()
        return result.rowcount or 0

    async def system_release(self, session_id: str) -> None:
        """Вернуть задачу в очередь (штатная остановка воркера на середине)."""
        session = await self.system_get(session_id)
        if session is None:
            return
        session.status = SessionStatus.QUEUED
        session.locked_at = None
        await self._db.commit()
