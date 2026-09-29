"""End-to-end check that RulesMatrixBuilder's per-document extraction really
goes through AIAssistantService (retry/merge included) and that the
"latest ДС wins" precedence still comes out correctly once the LLM call is
routed through the shared orchestrator instead of a bespoke loop.
"""
from pathlib import Path

import pytest
from docx import Document

from document_assistant.ai.model import AIModel
from document_assistant.cargo.models import PolicySource
from document_assistant.cargo.policy_discovery import PolicyFolderScanner
from document_assistant.cargo.rules_matrix_builder import RulesMatrixBuilder


class StubMatrixModel(AIModel):
    """Returns a clause table whose text depends on call order, so the test
    can assert the LATEST ДС's extraction is what survives the merge."""

    def __init__(self):
        self.calls = 0

    def response(self, query: str) -> str:
        self.calls += 1
        text = {1: "оборудование", 2: "оборудование и запчасти", 3: "оборудование, запчасти и материалы"}[self.calls]
        return (
            "| Пункт (номер/название) | Актуальный текст/значение | Комментарий |\n"
            "|---|---|---|\n"
            f"| 9. Объект страхования | {text} | |\n"
        )


def _make_policy_layout(folder: Path) -> None:
    d = Document()
    d.add_paragraph("Условия генерального полиса.")
    d.save(folder / "ГП страхования грузов.docx")

    ds_dir = folder / "ДС"
    ds_dir.mkdir()
    for name, content in [
        ("ДС 1 (п.9).docx", "Дополнительное соглашение 1."),
        ("ДС 2 (п.9).docx", "Дополнительное соглашение 2."),
    ]:
        d = Document()
        d.add_paragraph(content)
        d.save(ds_dir / name)


class TestRulesMatrixBuilderThroughAIAssistantService:
    def test_latest_ds_wins_end_to_end(self, tmp_path: Path):
        _make_policy_layout(tmp_path)
        sources = PolicyFolderScanner().scan(str(tmp_path))
        assert [s.kind for s in sources] == ["policy", "ds", "ds"]

        model = StubMatrixModel()
        builder = RulesMatrixBuilder(model=model)

        matrix = builder.build(str(tmp_path), sources)

        assert len(matrix.clauses) == 1
        assert matrix.clauses[0].effective_text == "оборудование, запчасти и материалы"
        assert "2" in matrix.clauses[0].source_label
        assert model.calls == 3  # one call per source document

    def test_debug_files_written_next_to_each_source(self, tmp_path: Path):
        """AIAssistantService's debug/JSON cache writers should fire for each
        policy/ДС document, same as they do for the DMS pipeline's client file."""
        _make_policy_layout(tmp_path)
        sources = PolicyFolderScanner().scan(str(tmp_path))

        RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)

        debug_files = list(tmp_path.rglob("*_llm_debug.md"))
        json_files = list(tmp_path.rglob("*_llm_output.json"))
        assert len(debug_files) == 3
        assert len(json_files) == 3


class TestUnreadableSourceResilience:
    """A single unreadable source (a stray Office lock file, a corrupted
    upload) must not lose the whole reconciliation run."""

    def test_broken_source_is_skipped_and_run_continues(self, tmp_path: Path):
        d = Document()
        d.add_paragraph("Условия генерального полиса.")
        d.save(tmp_path / "ГП полис.docx")
        (tmp_path / "broken.docx").write_text("not a real docx", encoding="utf-8")

        sources = [
            PolicySource(kind="policy", file_path=str(tmp_path / "ГП полис.docx")),
            PolicySource(kind="ds", file_path=str(tmp_path / "broken.docx"), ds_number=1),
        ]

        matrix = RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)

        assert len(matrix.clauses) == 1   # policy still processed

    def test_raises_only_when_every_source_fails(self, tmp_path: Path):
        (tmp_path / "broken.docx").write_text("not a real docx", encoding="utf-8")
        sources = [PolicySource(kind="policy", file_path=str(tmp_path / "broken.docx"))]

        with pytest.raises(RuntimeError, match="Не удалось обработать ни один документ"):
            RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)


class TestIncompleteMatrixIsFlagged:
    """A matrix missing the general policy holds only ДС amendments, so every
    declaration gets reconciled against clauses with no base text. The report
    then looks normal while being meaningless — the worst failure mode, and
    exactly what happened in production when a .doc policy failed to parse.
    """

    def _layout_with_broken_policy(self, tmp_path: Path) -> list[PolicySource]:
        (tmp_path / "ГП полис.docx").write_text("not a real docx", encoding="utf-8")
        d = Document()
        d.add_paragraph("ДС 1.")
        d.save(tmp_path / "ДС - 1.docx")
        return [
            PolicySource(kind="policy", file_path=str(tmp_path / "ГП полис.docx")),
            PolicySource(kind="ds", file_path=str(tmp_path / "ДС - 1.docx"), ds_number=1),
        ]

    def test_policy_failure_marks_matrix_incomplete(self, tmp_path: Path):
        sources = self._layout_with_broken_policy(tmp_path)

        matrix = RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)

        assert matrix.policy_processed is False
        assert matrix.is_complete is False
        assert len(matrix.clauses) == 1          # ДС still processed

    def test_ds_failure_alone_keeps_policy_flag_true(self, tmp_path: Path):
        d = Document()
        d.add_paragraph("Условия генерального полиса.")
        d.save(tmp_path / "ГП полис.docx")
        (tmp_path / "ДС - 1.docx").write_text("not a real docx", encoding="utf-8")

        sources = [
            PolicySource(kind="policy", file_path=str(tmp_path / "ГП полис.docx")),
            PolicySource(kind="ds", file_path=str(tmp_path / "ДС - 1.docx"), ds_number=1),
        ]

        matrix = RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)

        assert matrix.policy_processed is True
        assert matrix.is_complete is False       # ДС loss is still reported
        assert len(matrix.failed_sources) == 1

    def test_fully_successful_build_is_complete(self, tmp_path: Path):
        _make_policy_layout(tmp_path)
        sources = PolicyFolderScanner().scan(str(tmp_path))

        matrix = RulesMatrixBuilder(model=StubMatrixModel()).build(str(tmp_path), sources)

        assert matrix.is_complete is True
        assert matrix.failed_sources == []


class TestChunkSizeCap:
    """DocumentChunker splits by structure and ignores size: a policy of
    three large numbered sections went to the model as three huge requests,
    and the gateway answered 500 to them (29 times in one production log).
    """

    def test_oversized_chunks_are_split(self):
        chunks = [f"{i}. Раздел {i}\n" + "строка текста полиса\n" * 3000 for i in (1, 2, 3)]

        capped = RulesMatrixBuilder._cap_chunk_size(chunks, 20_000)

        assert len(capped) > len(chunks)
        assert max(len(c) for c in capped) <= 20_000

    def test_no_text_is_lost(self):
        chunks = [f"{i}. Раздел {i}\n" + "строка текста полиса\n" * 3000 for i in (1, 2, 3)]

        capped = RulesMatrixBuilder._cap_chunk_size(chunks, 20_000)

        assert "".join(capped) == "".join(chunks)

    def test_splits_on_line_boundaries(self):
        """A clause cut mid-line would reach the model as broken text."""
        chunks = ["строка полиса номер один\n" * 2000]

        capped = RulesMatrixBuilder._cap_chunk_size(chunks, 5_000)

        for part in capped[:-1]:
            assert part.endswith("\n")

    def test_small_chunks_pass_through_untouched(self):
        chunks = ["1. Короткий раздел", "2. Ещё один"]
        assert RulesMatrixBuilder._cap_chunk_size(chunks, 20_000) == chunks

    def test_zero_limit_disables_capping(self):
        chunks = ["x" * 100_000]
        assert RulesMatrixBuilder._cap_chunk_size(chunks, 0) == chunks
