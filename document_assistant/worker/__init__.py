"""Воркер: обработка сессий вне HTTP-запроса.

Очередь живёт в таблице sessions (см. SessionRepository.system_claim_next),
внешний брокер не используется. Запуск: ``python -m document_assistant.worker``
"""

from document_assistant.worker.tasks import process_dms_session

__all__ = ["process_dms_session"]
