from datetime import datetime, timezone

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import AIModel
from document_assistant.ai.preprocessor import DocumentChunker, ProcessingTask
from document_assistant.cargo.clause_merger import ClauseMerger
from document_assistant.cargo.matrix_postprocessor import CandidateBatch, MatrixPostProcessor, RawClause
from document_assistant.cargo.matrix_prompt import MatrixPromptEngine
from document_assistant.cargo.models import PolicySource, RulesMatrix
from document_assistant.cargo.preprocessors import ClauseExtractionPreprocessor
from document_assistant.cargo.report_export import CandidateReportExport
from document_assistant.core.parsers import DataParser
from document_assistant.core.settings import settings
from document_assistant.services.assistant import AIAssistantService


class RulesMatrixBuilder:
    """Builds the "матрица актуальных правил" from the general policy + all ДС.

    "Latest ДС wins" is decided by ClauseMerger — deterministic Python, not
    the LLM. The LLM's job here is narrow: extract the clauses out of ONE
    document at a time. That per-document extraction runs through
    AIAssistantService — the same retry/chunk-loop/merge orchestration the
    DMS pipeline and cargo's reconciliation step both use — rather than a
    bespoke loop.
    """

    def __init__(
        self,
        model: AIModel,
        prompt_engine: MatrixPromptEngine | None = None,
        postprocessor: MatrixPostProcessor | None = None,
        merger: ClauseMerger | None = None,
    ):
        self._model = model
        self._prompt_engine = prompt_engine or MatrixPromptEngine(
            role=settings.matrix_ai_role, template=settings.matrix_prompt_template,
        )
        self._postprocessor = postprocessor or MatrixPostProcessor()
        self._merger = merger or ClauseMerger()
        self._encoder = TextEncoder()
        self._chunker = DocumentChunker(batch_size=settings.llm_batch_size)

    def build(self, policy_folder: str, sources: list[PolicySource]) -> RulesMatrix:
        sources_with_candidates: list[tuple[PolicySource, list[RawClause]]] = [
            (source, self._extract_candidates(source)) for source in sources
        ]

        clauses = self._merger.merge(sources_with_candidates)

        return RulesMatrix(
            policy_folder=policy_folder,
            built_at=datetime.now(timezone.utc).isoformat(),
            clauses=clauses,
        )

    def _extract_candidates(self, source: PolicySource) -> list[RawClause]:
        text = self._encoder.prepared_data(DataParser(source.file_path).origin_data(source.file_path))
        chunks = self._chunker.split(text)

        task = ProcessingTask(request_id=0, file_path=source.file_path)
        service = AIAssistantService(
            preprocessor=ClauseExtractionPreprocessor(chunks, self._prompt_engine, source.clause_numbers or None),
            postprocessor=self._postprocessor,
            ai_model=self._model,
            report_export=CandidateReportExport(task),
            report_merge=CandidateBatch.merge,
        )
        result = service.result()
        return result["candidates"]
