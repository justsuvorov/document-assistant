from document_assistant.ai.model import AIModel
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor
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
        print(f"[INFO] Обработка {len(queries)} чанков", flush=True)

        reports = []
        for i, query in enumerate(queries, 1):
            print(f"[INFO] Чанк {i}/{len(queries)}...", flush=True)
            raw_response = self._model.response(query)
            reports.append(self._postprocessor.report(raw_response))

        report = InsuranceReport.merge(reports)
        return self._report_export.response(report)
