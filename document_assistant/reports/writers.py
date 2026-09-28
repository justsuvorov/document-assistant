import logging
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from document_assistant.reports.report_models import InsuranceReport, ReportRow



logger = logging.getLogger(__name__)

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


# Маркеры списка в начале ячейки: шаблоны часто вставлены из Word, где пункт
# выглядит как "·" + пачка неразрывных пробелов.
_LIST_MARKER = re.compile(r"^[·•▪◦●\-–—*]+\s*")
# Сокращение в конце требования: модель пишет "начало текста; ..." вместо
# полного текста длинной ячейки.
_TRAILING_ELLIPSIS = re.compile(r"[\s;,:]*(?:\.\.\.|…)\s*$")


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
        """Copy source file and write 3 annotation columns next to the client's data.

        - Колонки ответа ставятся ПОСЛЕ последнего заполненного столбца листа:
          в шаблоне клиента могут быть свои данные (например «комментарии ВСК»),
          затирать их нельзя.
        - Сопоставление последовательное: ответы модели идут в порядке документа,
          поэтому каждое требование сначала ищется ниже предыдущего найденного.
          Иначе одинаковые подзаголовки в разных разделах («Предоставляемые
          услуги:», «Не оказываются:») все указывали бы на первое вхождение.
        """
        shutil.copy2(source_path, output_path)
        wb = load_workbook(output_path)

        new_headers = ["Покрытие по программе", "Статус", "Комментарий"]

        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill("solid", fgColor=_HEADER)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        wrap = Alignment(vertical="top", wrap_text=True)
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # Первая свободная колонка каждого листа — считается до любых записей.
        ann_cols = {id(ws): self._last_used_column(ws) + 1 for ws in wb.worksheets}

        # Все строки-кандидаты в порядке документа (лист за листом, сверху вниз).
        # Одинаковые тексты НЕ схлопываются — у каждого вхождения своя позиция.
        candidates: list[tuple[str, tuple]] = []
        for ws in wb.worksheets:
            for row_idx in range(2, ws.max_row + 1):
                val = ws.cell(row=row_idx, column=1).value
                if val:
                    key = self._norm(str(val))
                    if key:
                        candidates.append((key, (ws, row_idx)))

        matched = 0
        unmatched: list[str] = []
        used: set[int] = set()
        cursor = -1
        sheets_touched: set = set()
        for row in report.rows:
            pos = self._find_row(row.client_requirement, candidates, used, cursor)
            if pos is None:
                if row.client_requirement.strip():
                    unmatched.append(row.client_requirement)
                continue
            used.add(pos)
            cursor = pos
            matched += 1
            ws, row_idx = candidates[pos][1]
            ann_col = ann_cols[id(ws)]
            sheets_touched.add(ws)

            cov_cell = ws.cell(row=row_idx, column=ann_col)
            if not isinstance(cov_cell, MergedCell):
                cov_cell.value = row.program_coverage
                cov_cell.alignment = wrap
                cov_cell.border = border

            status_cell = ws.cell(row=row_idx, column=ann_col + 1)
            if not isinstance(status_cell, MergedCell):
                status_cell.value = row.status
                status_cell.fill = PatternFill("solid", fgColor=_status_fill(row.status))
                status_cell.alignment = wrap
                status_cell.border = border

            comment_cell = ws.cell(row=row_idx, column=ann_col + 2)
            if not isinstance(comment_cell, MergedCell):
                comment_cell.value = row.comment
                comment_cell.alignment = wrap
                comment_cell.border = border

        # Add annotation headers to every sheet that received annotations
        for ws in sheets_touched:
            ann_col = ann_cols[id(ws)]
            for i, title in enumerate(new_headers):
                cell = ws.cell(row=1, column=ann_col + i)
                if isinstance(cell, MergedCell):
                    continue
                cell.value = title
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center
                ws.column_dimensions[cell.column_letter].width = [45, 14, 50][i]

        logger.info(
            f"Аннотировано {matched}/{len(report.rows)} строк LLM "
            f"из {len(candidates)} строк оригинала "
            f"({len(sheets_touched)} лист(ов)); не найдено в шаблоне: {len(unmatched)}")
        for text in unmatched:
            logger.debug(f"Не найдено в шаблоне: {text[:150]!r}")

        # Всегда добавляем полный ответ отдельным листом, независимо от того,
        # насколько удачно он лёг в шаблон клиента: сопоставление строк по
        # тексту эвристическое и на плохих/испорченных шаблонах может
        # промахнуться или проаннотировать не всё — на этом листе ответ
        # всегда полный и корректный.
        self._write_raw_answer_sheet(wb, report.rows)

        if report.summary:
            self._write_summary_sheet(wb, report.summary)

        wb.save(output_path)
        return output_path

    def _write_raw_answer_sheet(self, wb: Workbook, rows: list[ReportRow]) -> None:
        title = self._unique_title(wb, "Результат")
        ws = wb.create_sheet(title=title, index=0)
        self._write_header_row(ws)
        self._write_data_rows(ws, rows)
        self._apply_column_widths(ws)
        wb.active = wb.sheetnames.index(title)

    @staticmethod
    def _unique_title(wb: Workbook, base: str) -> str:
        if base not in wb.sheetnames:
            return base
        i = 2
        while f"{base} ({i})" in wb.sheetnames:
            i += 1
        return f"{base} ({i})"

    @staticmethod
    def _last_used_column(ws) -> int:
        """Последний столбец, где есть хоть одно значение (0 — лист пуст).

        ``ws.max_column`` не подходит: он учитывает и столбцы, где есть только
        форматирование, и тогда ответ уехал бы далеко вправо.
        """
        last = 0
        for row in ws.iter_rows(values_only=True):
            for col_idx in range(len(row), 0, -1):
                if row[col_idx - 1] not in (None, ""):
                    last = max(last, col_idx)
                    break
        return last

    @staticmethod
    def _norm(text: str) -> str:
        """Lowercase, collapse whitespace (incl. nbsp), drop a leading list marker."""
        text = " ".join(text.lower().split())
        return _LIST_MARKER.sub("", text)

    @staticmethod
    def _words(text: str) -> set[str]:
        return set(w for w in re.split(r"\W+", text.lower()) if len(w) > 2)

    def _find_row(
        self,
        requirement: str,
        candidates: list[tuple[str, tuple]],
        used: set[int],
        cursor: int,
    ) -> int | None:
        """Позиция строки шаблона для требования или None.

        Сначала ищем среди свободных строк ПОСЛЕ ``cursor`` (последней найденной),
        и только если там нет — среди всех свободных. Ответы модели идут в
        порядке документа, так что это разводит одинаковые тексты по разделам
        и не даёт похожей фразе «прилипнуть» к чужому разделу выше.
        """
        free = [(pos, key) for pos, (key, _) in enumerate(candidates) if pos not in used]
        ahead = [(pos, key) for pos, key in free if pos > cursor]
        found = self._match(requirement, ahead)
        if found is None:
            found = self._match(requirement, free)
        return found

    def _match(self, requirement: str, pool: list[tuple[int, str]]) -> int | None:
        """Match levels (first hit wins, in document order within each level):

        1. Exact — normalized strings are equal.
        2. Abbreviated — the LLM cut a long cell and ended it with "..." / "…";
           the source must start with the remaining text.
        3. Suffix — source key is the trailing part of the LLM key, separated by
           a punctuation char (LLM prepended section context), e.g.
           LLM: "Первичный…приёмы: аллерголог-иммунолог" / Source: "аллерголог-иммунолог".
        4. Prefix — source starts with the LLM key (LLM truncated without "...").
        5. Word-overlap ≥ 75 % — only for pairs whose word-count ratio is ≤ 3:1
           to avoid false positives from long shared prefixes.
        """
        key = self._norm(requirement)
        abbreviated = False
        while _TRAILING_ELLIPSIS.search(key):
            key = _TRAILING_ELLIPSIS.sub("", key)
            abbreviated = True
        if not key or len(key) < 5:
            return None

        for pos, orig in pool:
            if orig == key:
                return pos

        if abbreviated and len(key) >= 10:
            for pos, orig in pool:
                if orig.startswith(key):
                    return pos

        # Threshold ≥ 6 catches short specialist names (e.g. "невролог" = 8 chars)
        for pos, orig in pool:
            if 6 <= len(orig) < len(key) and key.endswith(orig):
                sep_idx = len(key) - len(orig) - 1
                if sep_idx < 0 or key[sep_idx] in (" ", ":", ",", ";", "."):
                    return pos

        # Only the direction where the LLM truncated the source row; the reverse
        # (LLM prepended context) is covered by the suffix level above.
        if len(key) >= 10:
            for pos, orig in pool:
                if orig.startswith(key):
                    return pos

        key_words = self._words(key)
        if len(key_words) < 3:
            return None
        best_score, best_pos = 0.0, None
        for pos, orig in pool:
            orig_words = self._words(orig)
            if not orig_words:
                continue
            shorter = min(len(key_words), len(orig_words))
            longer = max(len(key_words), len(orig_words))
            if longer > 3 * shorter:
                continue
            overlap = len(key_words & orig_words) / shorter
            if overlap > best_score:
                best_score, best_pos = overlap, pos
        return best_pos if best_score >= 0.75 else None

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
