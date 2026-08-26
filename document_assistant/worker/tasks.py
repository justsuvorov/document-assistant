"""arq-воркер: длинная LLM-обработка вне HTTP-запроса.

Схема одной задачи:
    S3 → временная папка → существующий AIAssistantService.result() → S3 → БД

Доменный код синхронный и блокирующий, поэтому запускается через
``asyncio.to_thread`` — иначе он заблокировал бы event loop воркера и
параллелизм WORKER_MAX_JOBS не работал бы.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path

from arq.connections import RedisSettings

from document_assistant.ai.preprocessor import ProcessingTask
from document_assistant.core.settings import settings
from document_assistant.db.engine import async_session_factory, dispose_engine
from document_assistant.db.repository import SessionRepository
from document_assistant.services.factory import build_dms_service
from document_assistant.storage import session_prefix, storage, workspace

# Суффиксы артефактов, которые AIAssistantService кладёт рядом с исходником.
_ARTIFACT_SUFFIXES = {
    "llm_output": "_llm_output.json",
    "llm_debug": "_llm_debug.md",
}


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def process_dms_session(ctx: dict, session_id: str) -> dict:
    """Обработать одну DMS-сессию. Вызывается arq по имени задачи."""
    async with async_session_factory() as db:
        repo = SessionRepository(db)
        session = await repo.system_get(session_id)
        if session is None:
            print(f"[WARN] Сессия {session_id} не найдена — задача пропущена", flush=True)
            return {"session_id": session_id, "status": "missing"}

        user_id = session.user_id
        client_key = session.input_keys.get("client")
        normative_key = session.input_keys.get("normative")
        max_chunks = session.max_chunks
        user_name = session.user_name

        if not client_key:
            await repo.system_mark_error(session_id, "В сессии нет входного файла клиента")
            return {"session_id": session_id, "status": "error"}

        await repo.system_mark_processing(session_id)

        try:
            result = await asyncio.to_thread(
                _run_dms_pipeline,
                client_key,
                normative_key,
                max_chunks,
                user_name,
                session_prefix(user_id, session_id),
            )
        except Exception as e:
            print(f"[ERROR] Сессия {session_id}: {e}", flush=True)
            traceback.print_exc()
            await repo.system_mark_error(session_id, f"{type(e).__name__}: {e}")
            return {"session_id": session_id, "status": "error"}

        await repo.system_mark_done(session_id, result["output_key"], result["artifact_keys"])
        print(f"[INFO] Сессия {session_id} готова: {result['output_key']}", flush=True)
        return {"session_id": session_id, "status": "done", "output_key": result["output_key"]}


def _run_dms_pipeline(
    client_key: str,
    normative_key: str | None,
    max_chunks: int,
    user_name: str | None,
    prefix: str,
) -> dict:
    """Синхронная часть: скачать, обработать, залить. Выполняется в потоке.

    Загрузка результатов в S3 происходит здесь же — до выхода из ``workspace``,
    иначе временная папка уже была бы удалена. ``prefix`` передаётся аргументом,
    а не берётся из глобального состояния: задач в воркере несколько
    одновременно (WORKER_MAX_JOBS), и общий префикс они бы затирали.
    """
    with workspace() as tmp:
        local_input = storage.download_to_tmp(client_key, dest_dir=tmp)
        print(f"[INFO] Вход скачан из S3: {client_key} → {local_input.name}", flush=True)

        # Нормативка — в отдельную подпапку: доменный код складывает все
        # артефакты рядом с клиентским файлом, и посторонний файл в той же
        # папке только запутывал бы сбор результатов.
        local_normative: str | None = None
        if normative_key:
            local_normative = str(
                storage.download_to_tmp(normative_key, dest_dir=tmp / "normative")
            )
            print(f"[INFO] Нормативка сессии: {normative_key}", flush=True)

        task = ProcessingTask(
            # ProcessingTask ожидает int; идентичность сессии несёт session_id,
            # request_id остаётся только для совместимости с форматом отчёта.
            request_id=int(time.time()),
            file_path=str(local_input),
            user_name=user_name,
        )
        response = build_dms_service(task, normative_base=local_normative).result(
            max_chunks_override=max_chunks
        )

        output_path = Path(response["output_file"])
        if not output_path.exists():
            raise FileNotFoundError(f"Отчёт не создан: {output_path}")
        result_key = f"{prefix}/output/{output_path.name}"
        storage.upload_file(output_path, result_key)

        artifact_keys: dict[str, str] = {}
        for name, suffix in _ARTIFACT_SUFFIXES.items():
            candidate = local_input.with_name(local_input.stem + suffix)
            if candidate.exists():
                key = f"{prefix}/output/{candidate.name}"
                storage.upload_file(candidate, key)
                artifact_keys[name] = key

        return {"output_key": result_key, "artifact_keys": artifact_keys}


async def startup(ctx: dict) -> None:
    storage.ensure_bucket()
    print(f"[INFO] arq-воркер запущен, бакет {settings.s3_bucket}", flush=True)


async def shutdown(ctx: dict) -> None:
    await dispose_engine()


class WorkerSettings:
    """Точка входа: ``arq document_assistant.worker.tasks.WorkerSettings``."""

    functions = [process_dms_session]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    keep_result = 3600

    @staticmethod
    def redis_settings() -> RedisSettings:
        return redis_settings()
