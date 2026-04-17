import pytest
from pathlib import Path

from document_assistant.ai.promt_builders import NormativeBaseLoader, PromptEngine


TEMPLATE = (
    "{role}\n\n"
    "## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n"
    "## ПРИМЕРЫ:\n{examples}\n\n"
    "## ЗАПРОС:\n{source_text}\n\n"
    "## ОТВЕТ:"
)
ROLE = "Ты специалист по страхованию."


# ── NormativeBaseLoader ───────────────────────────────────────────────────────

class TestNormativeBaseLoader:
    def test_empty_path_returns_empty(self):
        assert NormativeBaseLoader().load("") == ""

    def test_nonexistent_path_returns_empty(self):
        assert NormativeBaseLoader().load("/nonexistent/path/file.txt") == ""

    def test_loads_txt_file(self, normative_txt):
        content = NormativeBaseLoader().load(str(normative_txt))
        assert "Программа А" in content

    def test_loads_directory(self, tmp_path):
        (tmp_path / "prog1.txt").write_text("Программа 1", encoding="utf-8")
        (tmp_path / "prog2.md").write_text("# Программа 2", encoding="utf-8")
        content = NormativeBaseLoader().load(str(tmp_path))
        assert "Программа 1" in content
        assert "Программа 2" in content

    def test_directory_skips_unsupported_files(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b,c")
        (tmp_path / "notes.txt").write_text("Заметки", encoding="utf-8")
        content = NormativeBaseLoader().load(str(tmp_path))
        assert "a,b,c" not in content
        assert "Заметки" in content


# ── PromptEngine ──────────────────────────────────────────────────────────────

class TestPromptEngine:
    def _engine(self, normative_path=""):
        return PromptEngine(role=ROLE, template=TEMPLATE, normative_base=normative_path)

    def test_build_contains_role(self):
        prompt = self._engine().build(source_text="запрос", examples=[])
        assert ROLE in prompt

    def test_build_contains_source_text(self):
        prompt = self._engine().build(source_text="требования клиента", examples=[])
        assert "требования клиента" in prompt

    def test_build_without_examples(self):
        prompt = self._engine().build(source_text="текст", examples=[])
        assert "Пример" not in prompt

    def test_build_with_examples(self):
        examples = ["Запрос: А\nОтвет: Б", "Запрос: В\nОтвет: Г"]
        prompt = self._engine().build(source_text="текст", examples=examples)
        assert "Пример 1" in prompt
        assert "Пример 2" in prompt

    def test_normative_base_included(self, normative_txt):
        engine = PromptEngine(
            role=ROLE,
            template=TEMPLATE,
            normative_base=str(normative_txt),
        )
        prompt = engine.build(source_text="запрос", examples=[])
        assert "Программа А" in prompt

    def test_missing_placeholder_raises(self):
        bad_template = "{role} {missing_key}"
        engine = PromptEngine(role=ROLE, template=bad_template, normative_base="")
        with pytest.raises(ValueError, match="Ошибка в шаблоне промпта"):
            engine.build(source_text="текст", examples=[])


# ── ExamplesLoader ────────────────────────────────────────────────────────────

class TestExamplesLoader:
    def test_empty_path_returns_empty_list(self):
        from document_assistant.ai.preprocessor import ExamplesLoader
        assert ExamplesLoader().load("") == []

    def test_nonexistent_path_returns_empty_list(self):
        from document_assistant.ai.preprocessor import ExamplesLoader
        assert ExamplesLoader().load("/nonexistent") == []

    def test_loads_example_pair(self, examples_dir):
        from document_assistant.ai.preprocessor import ExamplesLoader
        examples = ExamplesLoader().load(str(examples_dir))
        assert len(examples) == 1
        assert "Запрос клиента" in examples[0]
        assert "Ответ специалиста" in examples[0]

    def test_skips_folder_with_wrong_file_count(self, tmp_path):
        from document_assistant.ai.preprocessor import ExamplesLoader
        sub = tmp_path / "bad_example"
        sub.mkdir()
        (sub / "only_one.txt").write_text("один файл")
        assert ExamplesLoader().load(str(tmp_path)) == []
