"""Интеграционные тесты веб-слоя: сессии, изоляция пользователей, статусы.

Хранилище настоящее — это просто каталог на диске, поэтому вместо заглушки
берётся временная папка: тест заодно проверяет реальную раскладку файлов.
Доменная логика (LLM) здесь не запускается: воркер тестируется отдельно, а его
результат имитируется через репозиторий.

Окружение (тестовая БД, отключённый Keycloak) настраивается в conftest.py.
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from document_assistant.auth.dependencies import (
    CurrentUser,
    get_current_user,
    require_user_page,
)
from document_assistant.core import settings as settings_module
from document_assistant.db.engine import async_session_factory
from document_assistant.db.models import Base
from document_assistant.db.repository import SessionRepository


@pytest.fixture
def storage_dir(tmp_path, monkeypatch) -> Path:
    """Каталог хранилища на время теста."""
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setattr(settings_module.settings, "storage_dir", str(root))
    return root


@pytest.fixture
def client(storage_dir):
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
    """Подменить текущего пользователя — и в API, и на HTML-страницах."""
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


def finish_session(session_id: str, storage_dir: Path, user_id: str = "alice") -> str:
    """Имитировать успешную работу воркера: файл на диске + статус done."""
    output_key = f"{user_id}/{session_id}/output/Запрос_ответ.xlsx"
    path = storage_dir / output_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"result-bytes")

    async def finish():
        async with async_session_factory() as db:
            await SessionRepository(db).system_mark_done(session_id, output_key, {})

    asyncio.run(finish())
    return output_key


def test_create_session_returns_immediately_and_queues(client, storage_dir):
    session_id = create_session(client)

    # Ответ приходит сразу со статусом queued — LLM не вызывалась.
    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["status"] == "queued"
    assert body["file_name"] == "Запрос.xlsx"

    # Файл лежит на диске по пути с user_id и session_id.
    assert (storage_dir / "alice" / session_id / "input" / "Запрос.xlsx").is_file()


def test_done_session_download_returns_file(client, storage_dir):
    session_id = create_session(client)
    finish_session(session_id, storage_dir)

    body = client.get(f"/api/sessions/{session_id}").json()
    assert body["status"] == "done"
    assert body["download_url"] == f"/api/sessions/{session_id}/download"

    # Ссылка ведёт на само приложение и реально отдаёт файл.
    downloaded = client.get(body["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"result-bytes"


def test_download_of_foreign_session_is_404(client, storage_dir):
    session_id = create_session(client, user_id="alice")
    finish_session(session_id, storage_dir)

    as_user("bob")
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404


def test_download_before_result_is_ready_returns_409(client):
    session_id = create_session(client)
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 409


def test_download_of_missing_file_returns_410(client, storage_dir):
    """Запись в БД есть, файла нет — не 500 и без раскрытия пути на диске."""
    session_id = create_session(client)
    output_key = finish_session(session_id, storage_dir)
    (storage_dir / output_key).unlink()

    response = client.get(f"/api/sessions/{session_id}/download")
    assert response.status_code == 410
    assert str(storage_dir) not in response.text


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


def test_filename_with_path_traversal_is_stripped(client, storage_dir):
    as_user("alice")
    response = client.post(
        "/api/sessions",
        files={"client_file": ("../../etc/passwd", b"x", "application/octet-stream")},
        data={"max_chunks": "0"},
    )
    assert response.status_code == 202
    session_id = response.json()["session_id"]

    # В путь попало только имя файла, и он остался внутри каталога сессии.
    assert (storage_dir / "alice" / session_id / "input" / "passwd").is_file()
    assert not (storage_dir.parent / "etc" / "passwd").exists()


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


def test_status_fragment_polls_while_running_and_stops_when_done(client, storage_dir):
    session_id = create_session(client)

    running = client.get(f"/pages/sessions/{session_id}/status")
    assert running.status_code == 200
    assert 'hx-trigger="every 2s"' in running.text

    finish_session(session_id, storage_dir)

    done = client.get(f"/pages/sessions/{session_id}/status")
    # Поллинг прекращается сам: в завершённом фрагменте нет hx-trigger.
    assert "hx-trigger" not in done.text
    assert f"/api/sessions/{session_id}/download" in done.text


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

    monkeypatch.setattr(settings_module.settings, "auth_disabled", False)
    assert client.get("/api/sessions").status_code == 401
