"""Тесты воркера: обвязка обработки, хранилище на диске и очередь в БД.

Сам AIAssistantService подменяется заглушкой: проверяется не качество отчёта
(это покрыто тестами доменной логики), а что вход забирается из хранилища,
артефакты собираются рядом с исходником и возвращаются обратно, и что задача
достаётся из очереди ровно один раз.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("NORMATIVE_BASE", "./normative_base")
os.environ.setdefault("AI_ROLE", "test-role")
os.environ.setdefault("AI_PROMPT_TEMPLATE", "{role}{normative_base}{examples}{source_text}")

from document_assistant.core import settings as settings_module  # noqa: E402
from document_assistant.db.engine import async_session_factory  # noqa: E402
from document_assistant.db.models import Base, SessionStatus  # noqa: E402
from document_assistant.db.repository import SessionRepository  # noqa: E402
from document_assistant.storage.local import LocalStorage, UnsafeKeyError  # noqa: E402
from document_assistant.worker import tasks  # noqa: E402


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, local_path, key):
        self.objects[key] = Path(local_path).read_bytes()

    def download_to_tmp(self, key, dest_dir=None):
        directory = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp())
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / Path(key).name
        path.write_bytes(self.objects[key])
        return path


class StubService:
    """Имитирует AIAssistantService.result(): пишет отчёт и артефакты рядом."""

    def __init__(self, source: Path):
        self._source = source

    def result(self, max_chunks_override=0):
        output = self._source.with_name(f"{self._source.stem}_ответ.xlsx")
        output.write_bytes(b"report")
        self._source.with_name(f"{self._source.stem}_llm_output.json").write_text(
            '{"chunks": []}', encoding="utf-8",
        )
        self._source.with_name(f"{self._source.stem}_llm_debug.md").write_text(
            "debug", encoding="utf-8",
        )
        return {"output_file": str(output)}


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(tasks, "storage", fake)
    return fake


# ── Обвязка обработки ───────────────────────────────────────────────────────


def test_pipeline_moves_input_and_artifacts_through_storage(storage, monkeypatch):
    storage.objects["alice/s1/input/Запрос.xlsx"] = b"client-data"

    captured = {}

    def fake_build(task, normative_base=None):
        captured["file_path"] = task.file_path
        captured["normative_base"] = normative_base
        return StubService(Path(task.file_path))

    monkeypatch.setattr(tasks, "build_dms_service", fake_build)

    result = tasks._run_dms_pipeline(
        client_key="alice/s1/input/Запрос.xlsx",
        normative_key=None,
        max_chunks=0,
        user_name="alice",
        prefix="alice/s1",
    )

    assert result["output_key"] == "alice/s1/output/Запрос_ответ.xlsx"
    assert result["artifact_keys"] == {
        "llm_output": "alice/s1/output/Запрос_llm_output.json",
        "llm_debug": "alice/s1/output/Запрос_llm_debug.md",
    }
    assert storage.objects[result["output_key"]] == b"report"

    # Без своей нормативки доменный код получает базу по умолчанию из settings.
    assert captured["normative_base"] is None


def test_per_session_normative_base_is_passed_to_domain(storage, monkeypatch):
    storage.objects["alice/s2/input/Запрос.xlsx"] = b"client-data"
    storage.objects["alice/s2/input/База.md"] = b"# rules"

    captured = {}

    def fake_build(task, normative_base=None):
        captured["normative_base"] = normative_base
        return StubService(Path(task.file_path))

    monkeypatch.setattr(tasks, "build_dms_service", fake_build)

    tasks._run_dms_pipeline(
        client_key="alice/s2/input/Запрос.xlsx",
        normative_key="alice/s2/input/База.md",
        max_chunks=0,
        user_name="alice",
        prefix="alice/s2",
    )

    normative_path = Path(captured["normative_base"])
    assert normative_path.name == "База.md"
    # Нормативка лежит в отдельной подпапке, чтобы не путаться с артефактами.
    assert normative_path.parent.name == "normative"


def test_workspace_is_cleaned_up(storage, monkeypatch):
    storage.objects["alice/s3/input/Запрос.xlsx"] = b"client-data"
    seen = {}

    def fake_build(task, normative_base=None):
        seen["dir"] = Path(task.file_path).parent
        return StubService(Path(task.file_path))

    monkeypatch.setattr(tasks, "build_dms_service", fake_build)
    tasks._run_dms_pipeline("alice/s3/input/Запрос.xlsx", None, 0, "alice", "alice/s3")

    # Промежуточные файлы не остаются на диске после обработки.
    assert not seen["dir"].exists()


def test_missing_report_raises(storage, monkeypatch):
    storage.objects["alice/s4/input/Запрос.xlsx"] = b"client-data"

    class NoOutput:
        def result(self, max_chunks_override=0):
            return {"output_file": "/nonexistent/Запрос_ответ.xlsx"}

    monkeypatch.setattr(tasks, "build_dms_service", lambda task, normative_base=None: NoOutput())

    with pytest.raises(FileNotFoundError):
        tasks._run_dms_pipeline("alice/s4/input/Запрос.xlsx", None, 0, "alice", "alice/s4")


# ── Хранилище на диске ──────────────────────────────────────────────────────


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setattr(settings_module.settings, "storage_dir", str(root))
    return LocalStorage()


def test_local_storage_roundtrip(local_storage, tmp_path):
    source = tmp_path / "Запрос.xlsx"
    source.write_bytes(b"payload")

    local_storage.upload_file(source, "alice/s1/input/Запрос.xlsx")
    assert local_storage.exists("alice/s1/input/Запрос.xlsx")

    restored = local_storage.download_to_tmp("alice/s1/input/Запрос.xlsx", tmp_path / "work")
    assert restored.read_bytes() == b"payload"
    assert restored.name == "Запрос.xlsx"


@pytest.mark.parametrize(
    "key",
    [
        "../outside.txt",
        "alice/../../outside.txt",
        "/etc/passwd",
        "alice/s1/../../../outside.txt",
    ],
)
def test_local_storage_rejects_keys_escaping_root(local_storage, key):
    """Ключ разворачивается в путь на диске — выход за каталог недопустим."""
    with pytest.raises(UnsafeKeyError):
        local_storage.resolve(key)


def test_local_storage_missing_object_raises(local_storage):
    with pytest.raises(FileNotFoundError):
        local_storage.download_to_tmp("alice/s1/input/нет.xlsx")
    with pytest.raises(FileNotFoundError):
        local_storage.path_for_download("alice/s1/output/нет.xlsx")


def test_delete_prefix_removes_whole_session(local_storage, tmp_path):
    source = tmp_path / "f.bin"
    source.write_bytes(b"x")
    local_storage.upload_file(source, "alice/s1/input/f.bin")
    local_storage.upload_file(source, "alice/s1/output/f.bin")
    local_storage.upload_file(source, "alice/s2/input/f.bin")

    local_storage.delete_prefix("alice/s1")

    assert not local_storage.exists("alice/s1/input/f.bin")
    assert not local_storage.exists("alice/s1/output/f.bin")
    # Соседняя сессия не задета.
    assert local_storage.exists("alice/s2/input/f.bin")


# ── Очередь в БД ────────────────────────────────────────────────────────────


async def _reset_schema() -> None:
    from document_assistant.db.engine import _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def clean_db():
    asyncio.run(_reset_schema())


def test_claim_takes_task_once_and_marks_processing(clean_db):
    """Захваченную задачу второй вызов уже не видит — иначе дубль обработки."""

    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            created = await repo.create(user_id="alice", input_keys={"client": "k"})

            first = await repo.system_claim_next()
            second = await repo.system_claim_next()
            return created.id, first, second

    session_id, first, second = asyncio.run(scenario())

    assert first is not None and first.id == session_id
    assert first.status is SessionStatus.PROCESSING
    assert first.attempts == 1
    assert first.locked_at is not None
    # Очередь пуста: та же задача повторно не выдаётся.
    assert second is None


def test_claim_returns_none_on_empty_queue(clean_db):
    async def scenario():
        async with async_session_factory() as db:
            return await SessionRepository(db).system_claim_next()

    assert asyncio.run(scenario()) is None


def test_claim_is_fifo(clean_db):
    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            first = await repo.create(user_id="alice", input_keys={"client": "a"})
            second = await repo.create(user_id="alice", input_keys={"client": "b"})
            claimed = await repo.system_claim_next()
            return first.id, second.id, claimed.id

    first_id, _second_id, claimed_id = asyncio.run(scenario())
    assert claimed_id == first_id


def test_stale_task_returns_to_queue(clean_db):
    """Воркер убит на середине — задача не должна висеть в processing вечно."""

    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            created = await repo.create(user_id="alice", input_keys={"client": "k"})
            await repo.system_claim_next()

            # stale_after=0 — любая захваченная задача считается брошенной.
            returned = await repo.system_requeue_stale(stale_after=0, max_attempts=3)
            refreshed = await repo.system_get(created.id)
            return returned, refreshed.status, refreshed.locked_at

    returned, status, locked_at = asyncio.run(scenario())
    assert returned == 1
    assert status is SessionStatus.QUEUED
    assert locked_at is None


def test_stale_task_becomes_error_after_max_attempts(clean_db):
    """Задача, роняющая воркер, уходит в error, а не крутится по кругу."""

    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            created = await repo.create(user_id="alice", input_keys={"client": "k"})

            for _ in range(3):
                await repo.system_claim_next()
                await repo.system_requeue_stale(stale_after=0, max_attempts=3)

            refreshed = await repo.system_get(created.id)
            return refreshed.status, refreshed.attempts, refreshed.error_message

    status, attempts, message = asyncio.run(scenario())
    assert status is SessionStatus.ERROR
    assert attempts == 3
    assert "попыток" in message


def test_fresh_task_is_not_reaped(clean_db):
    """Живая задача не должна отбираться у работающего воркера."""

    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            created = await repo.create(user_id="alice", input_keys={"client": "k"})
            await repo.system_claim_next()

            returned = await repo.system_requeue_stale(stale_after=3600, max_attempts=3)
            refreshed = await repo.system_get(created.id)
            return returned, refreshed.status

    returned, status = asyncio.run(scenario())
    assert returned == 0
    assert status is SessionStatus.PROCESSING


def test_mark_done_clears_lock(clean_db):
    async def scenario():
        async with async_session_factory() as db:
            repo = SessionRepository(db)
            created = await repo.create(user_id="alice", input_keys={"client": "k"})
            await repo.system_claim_next()
            await repo.system_mark_done(created.id, "alice/s/output/r.xlsx", {})
            refreshed = await repo.system_get(created.id)
            return refreshed.status, refreshed.locked_at

    status, locked_at = asyncio.run(scenario())
    assert status is SessionStatus.DONE
    # Снятая блокировка защищает готовую сессию от «воскрешения» reaper-ом.
    assert locked_at is None
