from pathlib import Path

from document_assistant.ai.preprocessor import ProcessingTask
from document_assistant.reports.report_models import InsuranceReport
from document_assistant.reports.writers import ExcelReportWriter, WordReportWriter, ReportWriter


class ReportExport:
    """Save InsuranceReport to a file in the same format as the client's input.

    Output file is placed next to the source file with an ``_ответ`` suffix:
        /some/path/request.xlsx  →  /some/path/request_ответ.xlsx

    Supported output formats: .xlsx, .xls, .docx, .doc
    For PDF and unknown formats the response falls back to Word (.docx).
    """

    _WRITERS: dict[str, type[ReportWriter]] = {
        ".xlsx": ExcelReportWriter,
        ".xls":  ExcelReportWriter,
        ".docx": WordReportWriter,
        ".doc":  WordReportWriter,
    }
    _FALLBACK_EXT = ".docx"

    def __init__(self, task: ProcessingTask):
        self._task = task

    def response(self, report: InsuranceReport) -> dict:
        output_path = self._build_output_path()
        writer = self._select_writer(output_path)
        saved_path = writer.write(report, output_path, Path(self._task.file_path))

        return {
            "request_id": self._task.request_id,
            "user_name": self._task.user_name,
            "output_file": str(saved_path),
        }

    def _build_output_path(self) -> Path:
        src = Path(self._task.file_path)
        ext = src.suffix.lower()

        if ext not in self._WRITERS:
            ext = self._FALLBACK_EXT

        return src.parent / f"{src.stem}_ответ{ext}"

    def _select_writer(self, output_path: Path) -> ReportWriter:
        writer_cls = self._WRITERS.get(output_path.suffix.lower(), WordReportWriter)
        return writer_cls()
