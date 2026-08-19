from pathlib import Path

from document_assistant.ai.preprocessor import ProcessingTask
from document_assistant.cargo.matrix_postprocessor import CandidateBatch
from document_assistant.cargo.models import ReconciliationReport
from document_assistant.cargo.output_paths import PeriodMonthResolver, ReconciliationOutputResolver
from document_assistant.cargo.reconciliation_writer import ReconciliationExcelWriter


class CandidateReportExport:
    """Export step used when AIAssistantService extracts clause candidates
    from a single policy/ДС document. There's nothing to write to disk at
    this stage — the candidates feed RulesMatrixBuilder/ClauseMerger, not a
    result file — so this just hands the merged CandidateBatch's rows back.
    Still needs a ``_task`` attribute: AIAssistantService's debug/JSON cache
    writers (_save_llm_debug/_save_llm_json) read the source file path off
    ``report_export._task.file_path``, same as the DMS ReportExport.
    """

    def __init__(self, task: ProcessingTask):
        self._task = task

    def response(self, batch: CandidateBatch) -> dict:
        return {"candidates": batch.rows}


class CargoReportExport:
    """Writes a ReconciliationReport for one declaration file — the cargo
    pipeline's counterpart to reports/report_export.py's ReportExport, using
    the "{номер} – результат проверки.xlsx" sibling-file naming convention
    instead of DMS's "{stem}_ответ{ext}".
    """

    def __init__(
        self,
        task: ProcessingTask,
        declaration_number: str,
        writer: ReconciliationExcelWriter | None = None,
    ):
        self._task = task
        self._declaration_number = declaration_number
        self._writer = writer or ReconciliationExcelWriter()

    def response(self, report: ReconciliationReport) -> dict:
        output_path = ReconciliationOutputResolver.resolve(self._task.file_path, self._declaration_number)
        self._writer.write(report, output_path)
        warning = PeriodMonthResolver.warn_if_mismatched(self._task.file_path, period_start=None)

        return {
            "request_id": self._task.request_id,
            "user_name": self._task.user_name,
            "declaration_path": self._task.file_path,
            "declaration_number": self._declaration_number,
            "row_count": len(report.rows),
            "output_file": str(output_path),
            "warnings": [w for w in [warning] if w],
        }
