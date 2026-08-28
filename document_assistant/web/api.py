"""HTTP-API сессий.

Все роуты защищены ``get_current_user``. Любое обращение к сессии идёт через
``repo.get_for_user(...)``, поэтому чужой session_id даёт 404 — без вариантов
получить 200 с чужими данными.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.preprocessor import DocumentChunker, ProcessingTask
from document_assistant.auth.dependencies import CurrentUser, get_current_user
from document_assistant.core.parsers import DataParser
from document_assistant.core.settings import settings
from document_assistant.db.models import SessionStatus
from document_assistant.db.repository import SessionRepository
from document_assistant.services.assistant import AIAssistantService
from document_assistant.storage import UnsafeKeyError, input_key, storage, workspace
from document_assistant.web.deps import get_db

router = APIRouter(prefix="/api", tags=["sessions"])

# Секунд на чанк — эмпирическая оценка из десктопной версии.
_SECONDS_PER_CHUNK = 120


async def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    """Сохранить загруженный файл во временную папку под безопасным именем.

    ``Path(...).name`` отсекает попытку передать путь в имени файла
    (``../../etc/passwd``) — иначе он попал бы в ключ, а тот теперь
    разворачивается в реальный путь на диске.
    """
    safe_name = Path(upload.filename or "upload.bin").name
    dest = dest_dir / safe_name
    dest.write_bytes(await upload.read())
    return dest


def _upload_all(items: list[tuple[Path, str]]) -> None:
    """Копирование файлов блокирующее — вызывается через asyncio.to_thread."""
    for local_path, key in items:
        storage.upload_file(local_path, key)


def _rebuild_sync(client_key: str, json_key: str, prefix: str, user_name: str | None) -> str:
    """Пересборка отчёта из кэша: хранилище → tmp → ReportExport → хранилище."""
    with workspace() as tmp:
        local_input = storage.download_to_tmp(client_key, dest_dir=tmp)
        local_json = storage.download_to_tmp(json_key, dest_dir=tmp / "cache")

        task = ProcessingTask(
            request_id=0,
            file_path=str(local_input),
            user_name=user_name,
        )
        result = AIAssistantService.rebuild_from_json(
            json_path=str(local_json),
            file_path=str(local_input),
            task=task,
        )
        output_path = Path(result["output_file"])
        new_key = f"{prefix}/{output_path.name}"
        storage.upload_file(output_path, new_key)
        return new_key


def _estimate_sync(local_path: Path) -> dict:
    raw = DataParser(str(local_path)).origin_data(str(local_path))
    encoded = TextEncoder().prepared_data(raw)
    chunks = DocumentChunker(batch_size=settings.llm_batch_size).split(encoded)
    return {
        "chunk_count": len(chunks),
        "estimated_seconds": len(chunks) * _SECONDS_PER_CHUNK,
        "total_chars": len(raw),
        "processed_chars": len(encoded),
    }


@router.post("/sessions", status_code=202)
async def create_session(
    client_file: UploadFile = File(..., description="Файл клиента"),
    normative_file: UploadFile | None = File(None, description="Нормативная база (опционально)"),
    max_chunks: int = Form(0, description="Максимум чанков, 0 = без ограничения"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принять файлы и сразу вернуть session_id.

    Очередь — это сама таблица sessions: строка со статусом queued и есть
    задача, воркер заберёт её сам. Отдельной постановки в брокер больше нет,
    поэтому и сценария «файлы сохранены, но задача потерялась» не существует.
    """
    repo = SessionRepository(db)
    session = await repo.create(
        user_id=user.user_id,
        user_name=user.user_name,
        input_keys={},
        max_chunks=max_chunks,
    )

    keys: dict[str, str] = {}
    try:
        with workspace() as tmp:
            local_client = await _save_upload(client_file, tmp)
            keys["client"] = input_key(user.user_id, session.id, local_client.name)

            local_norm = None
            if normative_file is not None and normative_file.filename:
                local_norm = await _save_upload(normative_file, tmp)
                keys["normative"] = input_key(user.user_id, session.id, local_norm.name)

            uploads = [(local_client, keys["client"])]
            if local_norm is not None:
                uploads.append((local_norm, keys["normative"]))
            await asyncio.to_thread(_upload_all, uploads)
    except Exception as e:
        await repo.system_mark_error(session.id, f"Не удалось сохранить файлы: {e}")
        raise HTTPException(status_code=507, detail=f"Ошибка записи в хранилище: {e}")

    # Ключи проставляются последними: до этого момента строка в queued есть,
    # но без input_keys — воркер такую отбракует с понятной ошибкой, а не
    # начнёт обрабатывать полузагруженную сессию.
    session.input_keys = keys
    await db.commit()

    return {"session_id": session.id, "status": SessionStatus.QUEUED.value}


@router.get("/sessions")
async def list_sessions(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История сессий текущего пользователя."""
    sessions = await SessionRepository(db).list_for_user(user.user_id)
    return {"sessions": [s.to_dict() for s in sessions]}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Статус сессии; при status=done — ссылка на скачивание результата."""
    session = await SessionRepository(db).get_for_user(session_id, user.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    payload = session.to_dict()
    if session.status is SessionStatus.DONE and session.output_key:
        # Файл отдаёт само приложение: хранилище лежит на диске сервера и
        # наружу не смотрит, поэтому прямых ссылок на него не существует.
        payload["download_url"] = f"/api/sessions/{session_id}/download"
    return payload


@router.post("/sessions/{session_id}/rebuild")
async def rebuild_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Пересобрать Excel из кэшированного LLM JSON, без обращения к модели.

    Владение проверяется через get_for_user до любого доступа к файлам — ключи
    берутся из записи сессии, а не из запроса, поэтому подставить чужой путь
    невозможно в принципе.
    """
    repo = SessionRepository(db)
    session = await repo.get_for_user(session_id, user.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    json_key = (session.artifact_keys or {}).get("llm_output")
    client_key = (session.input_keys or {}).get("client")
    if not json_key or not client_key:
        raise HTTPException(
            status_code=409,
            detail="Для этой сессии нет кэша LLM — пересборка невозможна",
        )

    prefix = f"{user.user_id}/{session_id}/output"
    try:
        new_key = await asyncio.to_thread(
            _rebuild_sync, client_key, json_key, prefix, session.user_name,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await repo.system_mark_done(session_id, new_key, session.artifact_keys or {})
    return {
        "session_id": session_id,
        "status": SessionStatus.DONE.value,
        "download_url": f"/api/sessions/{session_id}/download",
    }


@router.get("/sessions/{session_id}/download")
async def download_result(
    session_id: str,
    artifact: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отдать результат сессии.

    Ключ берётся из записи в БД, а не из запроса: пользователь не может
    назвать произвольный путь. Владение проверяется до обращения к диску,
    поэтому чужая сессия неотличима от несуществующей — 404.

    ``artifact`` (llm_output | llm_debug) отдаёт побочный артефакт вместо
    основного отчёта.
    """
    session = await SessionRepository(db).get_for_user(session_id, user.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    if artifact:
        key = (session.artifact_keys or {}).get(artifact)
        if key is None:
            raise HTTPException(status_code=404, detail=f"Артефакт {artifact} отсутствует")
    else:
        key = session.output_key
        if not key:
            raise HTTPException(status_code=409, detail="Результат ещё не готов")

    try:
        path = storage.path_for_download(key)
    except (FileNotFoundError, UnsafeKeyError):
        # Запись в БД есть, а файла нет — чистим статус в сообщении, но не
        # раскрываем путь на диске.
        raise HTTPException(status_code=410, detail="Файл результата недоступен")

    return FileResponse(path, filename=path.name)


@router.post("/estimate")
async def estimate(
    client_file: UploadFile = File(..., description="Файл клиента"),
    user: CurrentUser = Depends(get_current_user),
):
    """Оценить число чанков и время обработки. Без LLM, поэтому синхронно.

    Файл нигде не сохраняется: он нужен только чтобы посчитать чанки.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="da-est-") as tmp:
            local = await _save_upload(client_file, Path(tmp))
            return await asyncio.to_thread(_estimate_sync, local)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
