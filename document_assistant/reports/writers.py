import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from document_assistant.reports.report_models import InsuranceReport, ReportRow


# ── Colour palette ────────────────────────────────────────────────────────────

_GREEN  = "D6F0D6"   # Есть
_RED    = "F0D6D6"   # Нет
_YELLOW = "FFF3CD"   # Частично
_HEADER = "1F4E79"   # dark blue for header background

_STATUS_FILL = {
    "есть":      _GREEN,
    "нет":       _RED,
    "частично":  _YELLOW,
}


def _status_fill(status: str) -> str:
    return _STATUS_FILL.get(status.lower().strip(), "FFFFFF")


# ── Abstract base ─────────────────────────────────────────────────────────────

class ReportWriter(ABC):
    """Write an InsuranceReport to a file and return the output path."""

    HEADERS = [
        "Требование клиента",
        "Покрытие по программе",
        "Статус",
        "Комментарий",
    ]

    @abstractmethod
    def write(self, report: InsuranceReport, output_path: Path, source_path: Path = None) -> Path:
        pass


# ── Excel ─────────────────────────────────────────────────────────────────────

class ExcelReportWriter(ReportWriter):

    def write(self, report: InsuranceReport, output_path: Path, source_path: Path = None) -> Path:
        if source_path and source_path.suffix.lower() in (".xlsx", ".xls"):
            return self._write_annotated(report, output_path, source_path)
        return self._write_new(report, output_path)

    def _write_new(self, report: InsuranceReport, output_path: Path) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Сравнение"

        self._write_header_row(ws)
        self._write_data_rows(ws, report.rows)
        self._apply_column_widths(ws)

        if report.summary:
            self._write_summary_sheet(wb, report.summary)

        wb.save(output_path)
        return output_path

    def _write_annotated(self, report: InsuranceReport, output_path: Path, source_path: Path) -> Path:
        """Copy source file and append 3 annotation columns."""
        shutil.copy2(source_path, output_path)
        wb = load_workbook(output_path)
        ws = wb.active

        last_col = ws.max_column
        new_headers = ["Покрытие по программе", "Статус", "Комментарий"]

        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill("solid", fgColor=_HEADER)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        wrap = Alignment(vertical="top", wrap_text=True)
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for i, title in enumerate(new_headers):
            col = last_col + 1 + i
            cell = ws.cell(row=1, column=col, value=title)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
            ws.column_dimensions[cell.column_letter].width = [45, 14, 50][i]

        for row_idx, row in enumerate(report.rows, start=2):
            cov_cell = ws.cell(row=row_idx, column=last_col + 1, value=row.program_coverage)
            cov_cell.alignment = wrap
            cov_cell.border = border

            status_cell = ws.cell(row=row_idx, column=last_col + 2, value=row.status)
            status_cell.fill = PatternFill("solid", fgColor=_status_fill(row.status))
            status_cell.alignment = wrap
            status_cell.border = border

            comment_cell = ws.cell(row=row_idx, column=last_col + 3, value=row.comment)
            comment_cell.alignment = wrap
            comment_cell.border = border

        if report.summary:
            self._write_summary_sheet(wb, report.summary)

        wb.save(output_path)
        return output_path

    def _write_header_row(self, ws) -> None:
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill("solid", fgColor=_HEADER)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for col, title in enumerate(self.HEADERS, start=1):
            cell = ws.cell(row=1, column=col, value=title)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center

    def _write_data_rows(self, ws, rows: list[ReportRow]) -> None:
        wrap = Alignment(vertical="top", wrap_text=True)
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for row_idx, row in enumerate(rows, start=2):
            values = [
                row.client_requirement,
                row.program_coverage,
                row.status,
                row.comment,
            ]
            fill_color = _status_fill(row.status)
            fill = PatternFill("solid", fgColor=fill_color)

            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                cell.alignment = wrap
                cell.border = border
                if col == 3:          # Status column — coloured
                    cell.fill = fill

    @staticmethod
    def _apply_column_widths(ws) -> None:
        widths = [45, 45, 14, 50]
        for col, width in enumerate(widths, start=1):
            ws.column_dimensions[
                ws.cell(row=1, column=col).column_letter
            ].width = width

    @staticmethod
    def _write_summary_sheet(wb: Workbook, summary: str) -> None:
        ws = wb.create_sheet(title="Резюме")
        ws.column_dimensions["A"].width = 100
        cell = ws.cell(row=1, column=1, value=summary)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[1].height = max(15 * summary.count("\n") + 15, 40)


# ── Word ──────────────────────────────────────────────────────────────────────

class WordReportWriter(ReportWriter):

    def write(self, report: InsuranceReport, output_path: Path, source_path: Path = None) -> Path:
        doc = Document()

        heading = doc.add_heading("Анализ страхового покрытия", level=1)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

        self._write_table(doc, report.rows)

        if report.summary:
            doc.add_heading("Резюме", level=2)
            doc.add_paragraph(report.summary)

        doc.save(output_path)
        return output_path

    def _write_table(self, doc: Document, rows: list[ReportRow]) -> None:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"

        # Header row
        hdr_cells = table.rows[0].cells
        for i, title in enumerate(self.HEADERS):
            hdr_cells[i].text = title
            run = hdr_cells[i].paragraphs[0].runs[0]
            run.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            run.font.size = Pt(10)
            self._set_cell_background(hdr_cells[i], _HEADER)

        # Data rows
        _RGB = {
            _GREEN:  (0xD6, 0xF0, 0xD6),
            _RED:    (0xF0, 0xD6, 0xD6),
            _YELLOW: (0xFF, 0xF3, 0xCD),
        }

        for row in rows:
            cells = table.add_row().cells
            cells[0].text = row.client_requirement
            cells[1].text = row.program_coverage
            cells[2].text = row.status
            cells[3].text = row.comment

            fill = _status_fill(row.status)
            self._set_cell_background(cells[2], fill)

            for cell in cells:
                cell.paragraphs[0].runs[0].font.size = Pt(9)

    @staticmethod
    def _set_cell_background(cell, hex_color: str) -> None:
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tc_pr.append(shd)
