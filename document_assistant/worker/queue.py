"""Пул подключения к Redis на стороне API — только для постановки задач."""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis

from document_assistant.worker.tasks import redis_settings

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_dms_session(session_id: str) -> None:
    """Поставить сессию в очередь.

    ``_job_id`` = session_id делает постановку идемпотентной: повторный POST с
    тем же session_id не создаст второй задачи.
    """
    pool = await get_arq_pool()
    await pool.enqueue_job("process_dms_session", session_id, _job_id=f"dms:{session_id}")
