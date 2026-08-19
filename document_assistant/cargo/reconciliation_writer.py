import shutil
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side

from document_assistant.cargo.models import ReconciliationReport
from document_assistant.core.settings import settings
from document_assistant.reports.style import GREEN, RED, YELLOW
from document_assistant.reports.style import status_fill as _shared_status_fill
from document_assistant.reports.writers import ReportWriter

_STATUS_FILL = {
    "совпадает":     GREEN,
    "не совпадает":  RED,
    "не знаю":       YELLOW,
}


def _status_fill(status: str) -> str:
    return _shared_status_fill(status, _STATUS_FILL)


class ReconciliationExcelWriter(ReportWriter):
    """Writes a ReconciliationReport into a fresh copy of the fixed response
    template (``форма для результата ИИ.xlsx``) — unlike ExcelReportWriter,
    this never annotates an arbitrary source workbook (``source_path`` is
    accepted for ReportWriter-interface compatibility but unused), so the
    fragile row-matching heuristics in reports/writers.py do not apply here.
    """

    HEADERS = [
        "Номер декларации/строки",
        "Наименование поля в декларации",
        "С каким пунктом Ген. полиса сверено",
        "Результат проверки\n(совпадает/не совпадает/не знаю)",
        "Комментарий по сверке",
    ]

    def __init__(self, template_path: str | None = None, special_conditions_text: str = ""):
        self._template_path = template_path or settings.reconciliation_output_template_path
        self._special_conditions_text = special_conditions_text

    def write(self, report: ReconciliationReport, output_path: Path, source_path: Path = None) -> Path:
        if self._template_path and Path(self._template_path).exists():
            shutil.copy2(self._template_path, output_path)
            wb = load_workbook(output_path)
            ws = wb.active
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Лист1"
            self._write_headers(ws)

        self._write_rows(ws, report)

        if self._special_conditions_text:
            self._write_notes_sheet(wb, self._special_conditions_text)

        wb.save(output_path)
        return output_path

    def _write_headers(self, ws) -> None:
        for col, title in enumerate(self.HEADERS, start=1):
            ws.cell(row=1, column=col, value=title)

    def _write_rows(self, ws, report: ReconciliationReport) -> None:
        wrap = Alignment(vertical="top", wrap_text=True)
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        row_idx = 2
        for row in report.rows:
            values = [row.declaration_ref, row.field_name, row.matched_policy_clause, row.result, row.comment]
            fill = PatternFill("solid", fgColor=_status_fill(row.result))
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                cell.alignment = wrap
                cell.border = border
                if col == 4:  # Результат проверки — coloured
                    cell.fill = fill
            row_idx += 1

    @staticmethod
    def _write_notes_sheet(wb, text: str) -> None:
        ws = wb.create_sheet(title="Особые условия")
        ws.column_dimensions["A"].width = 100
        cell = ws.cell(row=1, column=1, value=text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
