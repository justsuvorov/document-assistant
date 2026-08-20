"""Integration tests using real files from examples/ and normative_base/."""
import pytest
from pathlib import Path

from document_assistant.ai.preprocessor import ExamplesLoader
from document_assistant.ai.promt_builders import NormativeBaseLoader, PromptEngine


PROJECT_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
NORMATIVE_DIR = PROJECT_ROOT / "normative_base"
NORMATIVE_DOCX = next(NORMATIVE_DIR.glob("*.docx"), None) if NORMATIVE_DIR.exists() else None

TEMPLATE = (
    "{role}\n\n"
    "## НОРМАТИВНАЯ БАЗА:\n{normative_base}\n\n"
    "## ПРИМЕРЫ:\n{examples}\n\n"
    "## ЗАПРОС:\n{source_text}\n\n"
    "## ОТВЕТ:"
)
ROLE = "Ты специалист по страхованию."


# ── Markers ────────────────────────────────────────────────────────────────────

requires_examples = pytest.mark.skipif(
    not EXAMPLES_DIR.exists(),
    reason="examples/ directory not found",
)
requires_normative = pytest.mark.skipif(
    NORMATIVE_DOCX is None,
    reason="normative_base/*.docx not found",
)


# ── ExamplesLoader — real files ────────────────────────────────────────────────

@requires_examples
class TestExamplesLoaderRealFiles:
    def setup_method(self):
        self.loader = ExamplesLoader()
        self.examples = self.loader.load(str(EXAMPLES_DIR))

    def test_loads_both_example_pairs(self):
        assert len(self.examples) == 2

    def test_each_example_has_client_section(self):
        for ex in self.examples:
            assert "Запрос клиента" in ex

    def test_each_example_has_response_section(self):
        for ex in self.examples:
            assert "Ответ специалиста" in ex

    def test_example1_from_excel_is_not_empty(self):
        # examples/1/ contains xlsx files — should parse to markdown tables
        assert len(self.examples[0]) > 50

    def test_example2_from_docx_is_not_empty(self):
        # examples/2/ contains docx files — should parse to text/tables
        assert len(self.examples[1]) > 50

    def test_excel_example_contains_table_markers(self):
        # Excel parser produces GitHub-flavored markdown tables
        assert "|" in self.examples[0]

    def test_examples_are_distinct(self):
        assert self.examples[0] != self.examples[1]


# ── NormativeBaseLoader — real docx file ──────────────────────────────────────

@requires_normative
class TestNormativeBaseLoaderRealFile:
    def setup_method(self):
        self.loader = NormativeBaseLoader()

    def test_loads_docx_file_directly(self):
        content = self.loader.load(str(NORMATIVE_DOCX))
        assert content != ""

    def test_docx_content_is_meaningful(self):
        content = self.loader.load(str(NORMATIVE_DOCX))
        assert len(content) > 100

    def test_loads_normative_directory(self):
        content = self.loader.load(str(NORMATIVE_DIR))
        assert content != ""

    def test_directory_includes_section_header(self):
        content = self.loader.load(str(NORMATIVE_DIR))
        # NormativeBaseLoader wraps each file as "### {file.stem}\n\n{content}"
        assert "###" in content

    def test_directory_section_header_matches_filename(self):
        content = self.loader.load(str(NORMATIVE_DIR))
        assert NORMATIVE_DOCX.stem in content


# ── PromptEngine — real normative base + real examples ────────────────────────

@requires_examples
@requires_normative
class TestPromptEngineWithRealData:
    def setup_method(self):
        self.engine = PromptEngine(
            role=ROLE,
            template=TEMPLATE,
            normative_base=str(NORMATIVE_DIR),
            num_ctx=500000,
        )
        self.examples = ExamplesLoader().load(str(EXAMPLES_DIR))

    def test_prompt_contains_role(self):
        prompt = self.engine.build(source_text="запрос клиента", examples=self.examples)
        assert ROLE in prompt

    def test_prompt_contains_normative_content(self):
        prompt = self.engine.build(source_text="запрос", examples=self.examples)
        assert NORMATIVE_DOCX.stem in prompt

    def test_prompt_contains_both_examples(self):
        prompt = self.engine.build(source_text="запрос", examples=self.examples)
        assert "Пример 1" in prompt
        assert "Пример 2" in prompt

    def test_prompt_contains_source_text(self):
        source = "требования по страхованию имущества"
        prompt = self.engine.build(source_text=source, examples=self.examples)
        assert source in prompt

    def test_full_prompt_is_substantial(self):
        prompt = self.engine.build(source_text="запрос", examples=self.examples)
        assert len(prompt) > 500
