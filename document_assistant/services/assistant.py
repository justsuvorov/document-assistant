from pathlib import Path

from document_assistant.ai.model import AIModel
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.reports.report_models import InsuranceReport


class AIAssistantService:
    def __init__(
        self,
        preprocessor: DocumentPreprocessor,
        postprocessor: PostProcessor,
        ai_model: AIModel,
        report_export: ReportExport,
    ):
        self._preprocessor = preprocessor
        self._postprocessor = postprocessor
        self._model = ai_model
        self._report_export = report_export

    def result(self) -> dict:
        queries = self._preprocessor.queries()
        if settings.llm_max_chunks > 0:
            queries = queries[:settings.llm_max_chunks]
        print(f"[INFO] Обработка {len(queries)} чанков", flush=True)

        reports = []
        debug_lines = []
        for i, query in enumerate(queries, 1):
            print(f"[INFO] Чанк {i}/{len(queries)}...", flush=True)
            raw_response = self._model.response(query)
            report = self._postprocessor.report(raw_response)
            reports.append(report)
            debug_lines.append(f"## Чанк {i} — {len(report.rows)} строк\n\n{raw_response}")

        self._save_llm_debug(debug_lines)


        report = InsuranceReport.merge(reports)
        return self._report_export.response(report)

    def _save_llm_debug(self, chunks: list[str]) -> None:
        try:
            file_path = Path(self._report_export._task.file_path)
            debug_path = file_path.with_name(file_path.stem + "_llm_debug.md")
            debug_path.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")
            print(f"[DEBUG] LLM ответы сохранены: {debug_path}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить LLM debug: {e}", flush=True)
