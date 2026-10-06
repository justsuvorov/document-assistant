"""Шаблон клиента → строки с ID и таблицы для модели."""

from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from document_assistant.filling.models import (
    ParsedTemplate,
    SheetTable,
    TableLine,
    TemplateRow,
    format_row_id,
)
from document_assistant.reports.writers import ExcelReportWriter

logger = logging.getLogger(__name__)


def _cell_text(value) -> str:
    if value is None:
        return ""
    # «|» и переносы ломают markdown-таблицу, которую видит модель.
    return " ".join(str(value).replace("|", "/").split())


class TemplateReader:
    """Читает .xlsx и выдаёт строки, на которые нужен ответ.

    - Скрытые листы и столбцы пропускаются: пользователь их не видит, а модель
      на скрытых листах (в КСК — списки клиник) только тратит токены.
      Скрытые строки НЕ пропускаются: чаще всего их скрыл автофильтр, и
      пропуск молча потерял бы требования.
    - Столбец требований определяется так же, как в старом пути
      (``ExcelReportWriter._requirement_column``).
    - ID получает каждая строка, начиная со 2-й, где в столбце требований есть
      текст. Остальные непустые строки идут в таблицу без ID — как контекст
      (шапка, детализация во вложенных столбцах).
    """

    def read(self, path: str | Path) -> ParsedTemplate:
        wb = load_workbook(path)
        rows: list[TemplateRow] = []
        tables: list[SheetTable] = []
        counter = 0

        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                logger.info(f"Лист {ws.title!r} скрыт — пропущен")
                continue

            hidden_cols = ExcelReportWriter._hidden_columns(ws)
            last_col = ExcelReportWriter._last_used_column(ws)
            if last_col == 0:
                continue
            req_col = ExcelReportWriter._requirement_column(ws)
            columns = [c for c in range(1, last_col + 1) if c not in hidden_cols]

            table = SheetTable(sheet=ws.title, columns=[get_column_letter(c) for c in columns])
            sheet_ids = 0
            for r in range(1, ws.max_row + 1):
                cells = [_cell_text(ws.cell(row=r, column=c).value) for c in columns]
                if not any(cells):
                    continue
                req_text = _cell_text(ws.cell(row=r, column=req_col).value)
                row_id = None
                if r >= 2 and req_text and req_col not in hidden_cols:
                    counter += 1
                    sheet_ids += 1
                    row_id = format_row_id(counter)
                    rows.append(TemplateRow(row_id=row_id, sheet=ws.title, row=r, text=req_text))
                table.lines.append(TableLine(row_id=row_id, cells=cells))

            if sheet_ids:
                tables.append(table)
                logger.info(
                    f"Лист {ws.title!r}: столбец требований {get_column_letter(req_col)}, "
                    f"строк с ID {sheet_ids}, скрытых столбцов {len(hidden_cols)}")

        return ParsedTemplate(rows=rows, tables=tables)

    @staticmethod
    def chunks(template: ParsedTemplate, batch_size: int) -> list[tuple[str, list[str]]]:
        """Таблицы для модели частями по ``batch_size`` строк с ID.

        Возвращает ``[(markdown, [ID в этой части]), ...]``. Строки без ID
        (детализация) остаются в той же части, что и строка с ID над ними.
        Шапка листа — строки до первого ID — повторяется в каждой части
        этого листа, иначе модели непонятно, что означают столбцы.
        """
        batch_size = max(1, batch_size)
        result: list[tuple[str, list[str]]] = []

        for table in template.tables:
            first_id = next(i for i, ln in enumerate(table.lines) if ln.row_id)
            preamble = table.lines[:first_id]
            body = table.lines[first_id:]

            groups: list[list[TableLine]] = []
            current: list[TableLine] = []
            ids_in_current = 0
            for line in body:
                if line.row_id and ids_in_current == batch_size:
                    groups.append(current)
                    current, ids_in_current = [], 0
                current.append(line)
                if line.row_id:
                    ids_in_current += 1
            if current:
                groups.append(current)

            for group in groups:
                md = TemplateReader._render(table, preamble + group)
                ids = [ln.row_id for ln in group if ln.row_id]
                result.append((md, ids))
        return result

    @staticmethod
    def _render(table: SheetTable, lines: list[TableLine]) -> str:
        header = ["ID"] + [f"Столбец {c}" for c in table.columns]
        out = [
            f"## Лист: {table.sheet}",
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for ln in lines:
            out.append("| " + " | ".join([ln.row_id or ""] + ln.cells) + " |")
        return "\n".join(out)
