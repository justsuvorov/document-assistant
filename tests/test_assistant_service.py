"""AIAssistantService is now the one orchestrator shared by the DMS and
cargo pipelines (see document_assistant/cargo/). These tests exercise it
directly with stub preprocessor/postprocessor/model/report_export — no real
LLM, no real files — to lock down the generalized contract: chunk_index is
threaded through to the postprocessor, a custom report_merge is honored, and
retry/skip-on-failure semantics are preserved.
"""
from dataclasses import dataclass, field

import pytest

from document_assistant.ai.model import AIModel
from document_assistant.services.assistant import AIAssistantService


@dataclass
class FakeReport:
    rows: list = field(default_factory=list)
    raw_text: str = ""

    @classmethod
    def merge(cls, reports: list["FakeReport"]) -> "FakeReport":
        rows = [r for rep in reports for r in rep.rows]
        return cls(rows=rows)


class ListPreprocessor:
    def __init__(self, queries: list[str]):
        self._queries = queries

    def queries(self) -> list[str]:
        return self._queries


class RecordingPostProcessor:
    """Records the chunk_index it was called with, for each raw_text."""

    def __init__(self):
        self.calls: list[tuple[str, int | None]] = []

    def report(self, raw_text: str, chunk_index: int | None = None) -> FakeReport:
        self.calls.append((raw_text, chunk_index))
        return FakeReport(rows=[raw_text])


class RecordingReportExport:
    def __init__(self):
        self.received = None

    def response(self, report: FakeReport) -> dict:
        self.received = report
        return {"row_count": len(report.rows)}


class StubModel(AIModel):
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = 0

    def response(self, query: str) -> str:
        self.calls += 1
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestChunkIndexThreading:
    def test_chunk_index_passed_in_call_order(self):
        postprocessor = RecordingPostProcessor()
        service = AIAssistantService(
            preprocessor=ListPreprocessor(["q1", "q2", "q3"]),
            postprocessor=postprocessor,
            ai_model=StubModel(["r1", "r2", "r3"]),
            report_export=RecordingReportExport(),
            report_merge=FakeReport.merge,
        )
        service.result()
        assert [idx for _, idx in postprocessor.calls] == [1, 2, 3]

    def test_chunk_index_reflects_true_position_even_when_earlier_chunk_skipped(self, monkeypatch):
        """Chunk 1 fails all 3 retries and is skipped — chunk 2 must still be
        reported with chunk_index=2, not 1."""
        monkeypatch.setattr("document_assistant.services.assistant.time.sleep", lambda _: None)
        postprocessor = RecordingPostProcessor()
        service = AIAssistantService(
            preprocessor=ListPreprocessor(["q1", "q2"]),
            postprocessor=postprocessor,
            ai_model=StubModel([RuntimeError("boom")] * 3 + ["r2"]),
            report_export=RecordingReportExport(),
            report_merge=FakeReport.merge,
        )
        service.result()
        assert [idx for _, idx in postprocessor.calls] == [2]


class TestCustomReportMerge:
    def test_uses_injected_merge_not_a_hardcoded_type(self):
        export = RecordingReportExport()
        service = AIAssistantService(
            preprocessor=ListPreprocessor(["q1", "q2"]),
            postprocessor=RecordingPostProcessor(),
            ai_model=StubModel(["r1", "r2"]),
            report_export=export,
            report_merge=FakeReport.merge,
        )
        result = service.result()
        assert result == {"row_count": 2}
        assert isinstance(export.received, FakeReport)


class TestFailureHandling:
    def test_raises_when_all_chunks_fail(self, monkeypatch):
        monkeypatch.setattr("document_assistant.services.assistant.time.sleep", lambda _: None)
        service = AIAssistantService(
            preprocessor=ListPreprocessor(["q1"]),
            postprocessor=RecordingPostProcessor(),
            ai_model=StubModel([RuntimeError("boom")] * 3),
            report_export=RecordingReportExport(),
            report_merge=FakeReport.merge,
        )
        with pytest.raises(RuntimeError):
            service.result()

    def test_max_chunks_override_limits_queries(self):
        postprocessor = RecordingPostProcessor()
        service = AIAssistantService(
            preprocessor=ListPreprocessor(["q1", "q2", "q3"]),
            postprocessor=postprocessor,
            ai_model=StubModel(["r1", "r2", "r3"]),
            report_export=RecordingReportExport(),
            report_merge=FakeReport.merge,
        )
        service.result(max_chunks_override=2)
        assert len(postprocessor.calls) == 2
