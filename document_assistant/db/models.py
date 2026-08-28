"""Модель сессии обработки — единственная таблица метаданных.

Сами файлы лежат на диске сервера; здесь только ключи, статус и владелец.
Эта же таблица служит очередью задач: воркер забирает строки со статусом
queued (см. SessionRepository.system_claim_next).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class SessionStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class SessionType(str, enum.Enum):
    """Тип задачи. Пока реализован только DMS.

    RECONCILE (сверка грузовых деклараций) заведён заранее, чтобы второй поток
    подключился как ещё один обработчик в воркере, без миграции схемы.
    """

    DMS = "dms"
    RECONCILE = "reconcile"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessingSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    # Отображаемое имя из токена — только для UI, правами не управляет.
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, values_callable=lambda e: [m.value for m in e]),
        default=SessionType.DMS,
        nullable=False,
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.QUEUED,
        index=True,
        nullable=False,
    )

    # Ключи входных файлов в хранилище: {"client": "...", "policy": "..."} — словарь, а не
    # список, чтобы воркер понимал роль каждого файла, а не полагался на порядок.
    input_keys: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Основной результат для скачивания (*_ответ.xlsx).
    output_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Побочные артефакты: *_llm_output.json (нужен для /api/rebuild), *_llm_debug.md.
    artifact_keys: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Поля очереди ────────────────────────────────────────────────────
    # Момент захвата задачи воркером. По нему находятся «повисшие» задачи:
    # если воркер убит в процессе, строка так и осталась бы в processing.
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Сколько раз задачу уже брали в работу — защита от вечного перезахвата
    # задачи, которая роняет воркер.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    @property
    def display_name(self) -> str:
        """Имя исходного файла клиента — то, по чему пользователь узнаёт сессию."""
        client_key = self.input_keys.get("client") if self.input_keys else None
        return client_key.rsplit("/", 1)[-1] if client_key else self.id

    def to_dict(self) -> dict:
        return {
            "session_id": self.id,
            "session_type": self.session_type.value,
            "status": self.status.value,
            "file_name": self.display_name,
            "error_message": self.error_message,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
