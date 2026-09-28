"""Изоляция нормативной базы: в контекст попадает только выбранный файл.

Бизнес-требование: если пользователь загрузил свою нормативку, модель должна
видеть именно её. Посторонние документы (чужие сессии, база по умолчанию,
примеры, файлы рядом на диске) в промт попадать не должны — иначе ответ
строится по чужим правилам страхования.
"""

from pathlib import Path

import pytest

from document_assistant.ai.promt_builders import NormativeBaseLoader, PromptEngine

TEMPLATE = "{role}\n\nБАЗА:\n{normative_base}\n\nПРИМЕРЫ:\n{examples}\n\nЗАПРОС:\n{source_text}"

SELECTED = "УНИКАЛЬНЫЙ-ТЕКСТ-ВЫБРАННОЙ-БАЗЫ"
DECOY = "ПОСТОРОННИЙ-ТЕКСТ-ЧУЖОГО-ФАЙЛА"


@pytest.fixture
def session_layout(tmp_path: Path) -> Path:
    """Раскладка, которую создаёт воркер: клиентский файл и нормативка в подпапке."""
    (tmp_path / "client.xlsx").write_text("запрос клиента", encoding="utf-8")

    normative_dir = tmp_path / "normative"
    normative_dir.mkdir()
    (normative_dir / "Выбранная.md").write_text(SELECTED, encoding="utf-8")

    # Посторонние файлы: рядом с клиентским и в соседней папке.
    (tmp_path / "Лишняя.md").write_text(DECOY, encoding="utf-8")
    other = tmp_path / "other_session"
    other.mkdir()
    (other / "Чужая.md").write_text(DECOY, encoding="utf-8")

    return tmp_path


class TestNormativeBaseLoader:
    def test_file_path_loads_only_that_file(self, session_layout: Path):
        text = NormativeBaseLoader().load(str(session_layout / "normative" / "Выбранная.md"))
        assert SELECTED in text
        assert DECOY not in text

    def test_directory_path_concatenates_all_files(self, tmp_path: Path):
        """Документируем обратное поведение: каталог читается целиком.

        Именно поэтому воркер передаёт путь к ФАЙЛУ, а не к папке сессии.
        """
        (tmp_path / "a.md").write_text(SELECTED, encoding="utf-8")
        (tmp_path / "b.md").write_text(DECOY, encoding="utf-8")

        text = NormativeBaseLoader().load(str(tmp_path))
        assert SELECTED in text and DECOY in text

    def test_missing_path_gives_empty(self, tmp_path: Path):
        assert NormativeBaseLoader().load(str(tmp_path / "нет.md")) == ""


class TestPromptIsolation:
    def test_prompt_contains_only_selected_normative(self, session_layout: Path):
        engine = PromptEngine(
            role="роль",
            template=TEMPLATE,
            normative_base=str(session_layout / "normative" / "Выбранная.md"),
            num_ctx=100_000,
        )
        prompt = engine.build(source_text="запрос клиента", examples=[])

        assert SELECTED in prompt, "выбранная пользователем база обязана быть в промте"
        assert DECOY not in prompt, "посторонние файлы не должны попадать в контекст"

    def test_examples_block_empty_when_not_passed(self, session_layout: Path):
        """Рабочий путь (`DocumentPreprocessor.queries`) передаёт examples=[]."""
        engine = PromptEngine(
            role="роль",
            template=TEMPLATE,
            normative_base=str(session_layout / "normative" / "Выбранная.md"),
            num_ctx=100_000,
        )
        prompt = engine.build(source_text="запрос", examples=[])

        assert "Пример 1" not in prompt
