"""Тест обвязки воркера: S3 → временная папка → доменный код → S3.

Сам AIAssistantService подменяется заглушкой: проверяется не качество отчёта
(это покрыто тестами доменной логики), а что вход скачивается, артефакты
собираются рядом с исходником и уезжают в S3 под ключами сессии.
"""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("NORMATIVE_BASE", "./normative_base")
os.environ.setdefault("AI_ROLE", "test-role")
os.environ.setdefault("AI_PROMPT_TEMPLATE", "{role}{normative_base}{examples}{source_text}")

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


def test_pipeline_moves_input_and_artifacts_through_s3(storage, monkeypatch):
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

    # Файлы не остаются на диске контейнера после обработки.
    assert not seen["dir"].exists()


def test_missing_report_raises(storage, monkeypatch):
    storage.objects["alice/s4/input/Запрос.xlsx"] = b"client-data"

    class NoOutput:
        def result(self, max_chunks_override=0):
            return {"output_file": "/nonexistent/Запрос_ответ.xlsx"}

    monkeypatch.setattr(tasks, "build_dms_service", lambda task, normative_base=None: NoOutput())

    with pytest.raises(FileNotFoundError):
        tasks._run_dms_pipeline("alice/s4/input/Запрос.xlsx", None, 0, "alice", "alice/s4")
