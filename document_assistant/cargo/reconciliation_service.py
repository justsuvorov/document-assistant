from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import AIModel, ModelFactory
from document_assistant.ai.preprocessor import DocumentChunker, ProcessingTask
from document_assistant.cargo.declaration_classifier import DeclarationType, DeclarationTypeClassifier
from document_assistant.cargo.filename_parsing import DeclarationFilenameParser
from document_assistant.cargo.models import ReconciliationReport, RulesMatrix
from document_assistant.cargo.preprocessors import DeclarationPreprocessor
from document_assistant.cargo.reconciliation_postprocessor import ReconciliationPostProcessor
from document_assistant.cargo.reconciliation_prompt import ReconciliationPromptEngine
from document_assistant.cargo.reconciliation_writer import ReconciliationExcelWriter
from document_assistant.cargo.report_export import CargoReportExport
from document_assistant.core.parsers import DataParser
from document_assistant.core.pydantic_models import ReconcileRequest
from document_assistant.core.settings import settings
from document_assistant.services.assistant import AIAssistantService


class CargoReconciliationService:
    """Orchestrates reconciling one or more declarations against a RulesMatrix.

    Each declaration file is delegated to its own AIAssistantService run —
    the same retry/chunk-loop/merge/export machinery the DMS pipeline uses —
    so this class only handles what's specific to cargo: classifying the
    declaration and wiring the cargo-specific preprocessor/postprocessor/
    report_export into AIAssistantService. (Classification happens here,
    not inside the preprocessor, because ReconciliationPostProcessor also
    needs to know single-vs-multi before AIAssistantService.result() runs.)
    """

    def __init__(
        self,
        rules_matrix: RulesMatrix,
        prompt_engine: ReconciliationPromptEngine,
        special_conditions_text: str,
        model: AIModel,
        classifier: DeclarationTypeClassifier | None = None,
        filename_parser: DeclarationFilenameParser | None = None,
    ):
        self._rules_matrix = rules_matrix
        self._prompt_engine = prompt_engine
        self._special_conditions_text = special_conditions_text
        self._model = model
        self._classifier = classifier or DeclarationTypeClassifier()
        self._filename_parser = filename_parser or DeclarationFilenameParser()

    @classmethod
    def default(cls, matrix: RulesMatrix, special_conditions_text: str) -> "CargoReconciliationService":
        return cls(
            rules_matrix=matrix,
            prompt_engine=ReconciliationPromptEngine(
                role=settings.reconciliation_ai_role,
                template=settings.reconciliation_prompt_template,
                rules_base_path=settings.reconciliation_rules_base,
            ),
            special_conditions_text=special_conditions_text,
            model=ModelFactory.create(),
        )

    def result(self, request: ReconcileRequest) -> dict:
        rules_matrix_block = self._rules_matrix.to_prompt_block()
        declarations_out = [
            self._process_declaration(decl_path, request, rules_matrix_block)
            for decl_path in request.declaration_paths
        ]

        return {
            "request_id": request.request_id,
            "user_name": request.user_name,
            "policy_folder": request.policy_folder,
            "matrix": {
                "clause_count": len(self._rules_matrix.clauses),
                "fingerprint": self._rules_matrix.fingerprint,
            },
            "declarations": declarations_out,
        }

    def _process_declaration(self, decl_path: str, request: ReconcileRequest, rules_matrix_block: str) -> dict:
        text = TextEncoder().prepared_data(DataParser(decl_path).origin_data(decl_path))
        decl_number = self._filename_parser.parse_number(decl_path) or "UNKNOWN"
        decl_type = self._classifier.classify(text)
        multi = decl_type is DeclarationType.MULTI

        chunks = DocumentChunker(batch_size=1).split(text) if multi else [text]

        task = ProcessingTask(request_id=request.request_id, file_path=decl_path, user_name=request.user_name)
        service = AIAssistantService(
            preprocessor=DeclarationPreprocessor(chunks, self._prompt_engine, rules_matrix_block, self._special_conditions_text),
            postprocessor=ReconciliationPostProcessor(decl_number, multi=multi),
            ai_model=self._model,
            report_export=CargoReportExport(
                task, decl_number, ReconciliationExcelWriter(special_conditions_text=self._special_conditions_text),
            ),
            report_merge=ReconciliationReport.merge,
        )
        result = service.result(max_chunks_override=request.max_chunks)
        result["type"] = decl_type.value
        result["line_items"] = len(chunks) if multi else 1
        return result
