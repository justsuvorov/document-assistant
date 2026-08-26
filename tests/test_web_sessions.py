"""Интеграционные тесты веб-слоя: сессии, изоляция пользователей, статусы.

S3 и очередь подменяются заглушками — проверяется поведение приложения, а не
доступность инфраструктуры. Доменная логика (LLM) здесь не запускается:
воркер тестируется отдельно, а его результат имитируется через репозиторий.

Окружение (тестовая БД, отключённый Keycloak) настраивается в conftest.py.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from document_assistant.auth.dependencies import (
    CurrentUser,
    get_current_user,
    require_user_page,
)
from document_assistant.db.engine import async_session_factory
from document_assistant.db.models import Base
from document_assistant.db.repository import SessionRepository
from document_assistant.web import api as api_module


class FakeStorage:
    """Хранилище в памяти: ключ → содержимое."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self):
        pass

    def upload_file(self, local_path, key):
        self.objects[key] = Path(local_path).read_bytes()

    def download_to_tmp(self, key, dest_dir=None):
        directory = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp())
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / Path(key).name
        path.write_bytes(self.objects[key])
        return path

    def presigned_url(self, key, expires=None):
        return f"https://s3.test/{key}?signature=stub"


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(api_module, "storage", fake)
    monkeypatch.setattr(main, "storage", fake)
    import document_assistant.web.pages as pages_module

    monkeypatch.setattr(pages_module, "storage", fake)
    return fake


@pytest.fixture
def enqueued(monkeypatch):
    """Перехватывает постановку в очередь — Redis в тестах не нужен."""
    calls: list[str] = []

    async def fake_enqueue(session_id: str) -> None:
        calls.append(session_id)

    monkeypatch.setattr(api_module, "enqueue_dms_session", fake_enqueue)
    return calls


@pytest.fixture
def client(storage, enqueued):
    # Схема пересоздаётся на каждый тест: удалять файл БД нельзя — движок
    # уже держит на него открытое соединение.
    asyncio.run(_reset_schema())
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


async def _reset_schema() -> None:
    from document_assistant.db.engine import _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def as_user(user_id: str) -> None:
    """Подменить текущего пользователя — и в API, и на HTML-страницах.

    Переопределяются обе зависимости: /api/* использует get_current_user,
    страницы — require_user_page (он редиректит вместо 401).
    """
    user = CurrentUser(user_id=user_id, user_name=user_id)
    main.app.dependency_overrides[get_current_user] = lambda: user
    main.app.dependency_overrides[require_user_page] = lambda: user


def create_session(client, user_id: str = "alice") -> str:
    as_user(user_id)
    response = client.post(
        "/api/sessions",
        files={"client_file": ("Запрос.xlsx", b"stub-content", "application/vnd.ms-excel")},
        data={"max_chunks": "0"},
    )
    assert response.status_code == 202, response.text
    return response.json()["session_id"]


def test_create_session_returns_immediately_and_enqueues(client, enqueued, storage):
    session_id = create_session(client)

    # Ответ приходит сразу со статусом queued — LLM не вызывалась.
    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["status"] == "queued"
    assert body["file_name"] == "Запрос.xlsx"

    assert enqueued == [session_id]
    # Файл ушёл в S3 под ключом с user_id и session_id, а не на диск.
    assert f"alice/{session_id}/input/Запрос.xlsx" in storage.objects


def test_done_session_exposes_presigned_download_url(client, storage):
    session_id = create_session(client)
    output_key = f"alice/{session_id}/output/Запрос_ответ.xlsx"
    storage.objects[output_key] = b"result"

    async def finish():
        async with async_session_factory() as db:
            await SessionRepository(db).system_mark_done(session_id, output_key, {})

    asyncio.run(finish())

    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["status"] == "done"
    assert body["download_url"].startswith(f"https://s3.test/{output_key}")


def test_other_user_cannot_read_foreign_session(client):
    session_id = create_session(client, user_id="alice")

    as_user("bob")
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.get(f"/pages/sessions/{session_id}/status").status_code == 404
    assert client.post(f"/api/sessions/{session_id}/rebuild").status_code == 404


def test_session_list_is_scoped_to_current_user(client):
    alice_session = create_session(client, user_id="alice")
    bob_session = create_session(client, user_id="bob")

    as_user("alice")
    alice_ids = [s["session_id"] for s in client.get("/api/sessions").json()["sessions"]]
    assert alice_ids == [alice_session]

    as_user("bob")
    bob_ids = [s["session_id"] for s in client.get("/api/sessions").json()["sessions"]]
    assert bob_ids == [bob_session]


def test_filename_with_path_traversal_is_stripped(client, storage):
    as_user("alice")
    response = client.post(
        "/api/sessions",
        files={"client_file": ("../../etc/passwd", b"x", "application/octet-stream")},
        data={"max_chunks": "0"},
    )
    assert response.status_code == 202
    session_id = response.json()["session_id"]
    # В ключ попало только имя файла — выйти за пределы префикса нельзя.
    assert f"alice/{session_id}/input/passwd" in storage.objects


def test_rebuild_without_llm_cache_returns_conflict(client):
    session_id = create_session(client)
    assert client.post(f"/api/sessions/{session_id}/rebuild").status_code == 409


def test_index_page_renders_upload_form_and_history(client):
    session_id = create_session(client)
    page = client.get("/")
    assert page.status_code == 200
    assert 'name="client_file"' in page.text
    assert 'hx-post="/api/sessions"' in page.text
    assert session_id in page.text


def test_status_fragment_polls_while_running_and_stops_when_done(client, storage):
    session_id = create_session(client)

    running = client.get(f"/pages/sessions/{session_id}/status")
    assert running.status_code == 200
    assert 'hx-trigger="every 2s"' in running.text

    output_key = f"alice/{session_id}/output/Запрос_ответ.xlsx"
    storage.objects[output_key] = b"result"

    async def finish():
        async with async_session_factory() as db:
            await SessionRepository(db).system_mark_done(session_id, output_key, {})

    asyncio.run(finish())

    done = client.get(f"/pages/sessions/{session_id}/status")
    # Поллинг прекращается сам: в завершённом фрагменте нет hx-trigger.
    assert "hx-trigger" not in done.text
    assert "https://s3.test/" in done.text


def test_status_fragment_shows_error_message(client):
    session_id = create_session(client)

    async def fail():
        async with async_session_factory() as db:
            await SessionRepository(db).system_mark_error(session_id, "Qwen недоступен")

    asyncio.run(fail())

    fragment = client.get(f"/pages/sessions/{session_id}/status")
    assert "Qwen недоступен" in fragment.text
    assert "hx-trigger" not in fragment.text


def test_api_requires_auth_when_enabled(client, monkeypatch):
    """С включённой авторизацией и без токена API отвечает 401, а не 200."""
    main.app.dependency_overrides.clear()
    from document_assistant.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "auth_disabled", False)
    assert client.get("/api/sessions").status_code == 401
