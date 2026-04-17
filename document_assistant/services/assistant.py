from document_assistant.ai.model import AIModel
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import Preprocessor
from document_assistant.reports.report_export import ReportExport


class AIAssistantService:
    def __init__(
        self,
        preprocessor: Preprocessor,
        postprocessor: PostProcessor,
        ai_model: AIModel,
        report_export: ReportExport,
    ):
        self._preprocessor = preprocessor
        self._postprocessor = postprocessor
        self._model = ai_model
        self._report_export = report_export

    def result(self) -> dict:
        query = self._preprocessor.query()
        raw_response = self._model.response(query)
        report = self._postprocessor.report(raw_response)
        return self._report_export.response(report)
