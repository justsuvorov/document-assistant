from datetime import datetime, timezone
from pathlib import Path

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
        # One unreadable source must not lose the whole run: a single stray
        # Office lock file («~$ДС - 1.docx») used to abort reconciliation for
        # every declaration. Such a source is skipped, loudly.
        sources_with_candidates: list[tuple[PolicySource, list[RawClause]]] = []
        failed: list[str] = []
        policy_processed = not any(s.kind == "policy" for s in sources)
        for source in sources:
            try:
                sources_with_candidates.append((source, self._extract_candidates(source)))
                if source.kind == "policy":
                    policy_processed = True
            except Exception as e:
                failed.append(f"{source.label} ({Path(source.file_path).name}): {e}")
                print(
                    f"[ERROR] {source.label}: не удалось обработать "
                    f"{Path(source.file_path).name} — {e}. Источник пропущен.",
                    flush=True,
                )

        if not sources_with_candidates:
            raise RuntimeError(
                "Не удалось обработать ни один документ полиса/ДС: " + "; ".join(failed)
            )
        if failed:
            print(
                f"[WARN] Матрица правил построена без {len(failed)} источник(ов) из {len(sources)}",
                flush=True,
            )
        if not policy_processed:
            print(
                "[ERROR] Генеральный полис не попал в матрицу правил — "
                "сверка по такой матрице недостоверна",
                flush=True,
            )

        clauses = self._merger.merge(sources_with_candidates)

        return RulesMatrix(
            policy_folder=policy_folder,
            built_at=datetime.now(timezone.utc).isoformat(),
            clauses=clauses,
            policy_processed=policy_processed,
            failed_sources=failed,
        )

    @staticmethod
    def _cap_chunk_size(chunks: list[str], limit: int) -> list[str]:
        """Split oversized chunks on line boundaries.

        DocumentChunker splits by structure only: a policy made of three big
        numbered sections yields three chunks of any size, and the gateway
        answers 500 to the largest of them. Nothing here changes what the
        model is asked — only how much it is asked at once.
        """
        if not limit:
            return chunks

        capped: list[str] = []
        for chunk in chunks:
            if len(chunk) <= limit:
                capped.append(chunk)
                continue
            current: list[str] = []
            used = 0
            for line in chunk.splitlines(keepends=True):
                if used + len(line) > limit and current:
                    capped.append("".join(current))
                    current, used = [], 0
                current.append(line)
                used += len(line)
            if current:
                capped.append("".join(current))
        return capped

    def _extract_candidates(self, source: PolicySource) -> list[RawClause]:
        print(f"[INFO] Обработка: {source.label} ({Path(source.file_path).name})", flush=True)
        text = self._encoder.prepared_data(DataParser(source.file_path).origin_data(source.file_path))
        chunks = self._chunker.split(text)

        limit = settings.matrix_chunk_max_chars
        capped = self._cap_chunk_size(chunks, limit)
        if len(capped) != len(chunks):
            print(
                f"[INFO] {source.label}: чанки крупнее {limit} символов разделены "
                f"({len(chunks)} → {len(capped)}), чтобы запрос не отклонялся моделью",
                flush=True,
            )
        chunks = capped

        task = ProcessingTask(request_id=0, file_path=source.file_path)
        service = AIAssistantService(
            preprocessor=ClauseExtractionPreprocessor(chunks, self._prompt_engine, source.clause_numbers or None),
            postprocessor=self._postprocessor,
            ai_model=self._model,
            report_export=CandidateReportExport(task),
            report_merge=CandidateBatch.merge,
        )
        result = service.result()
        candidates = result["candidates"]
        print(f"[INFO] {source.label}: извлечено пунктов — {len(candidates)}", flush=True)
        return candidates
