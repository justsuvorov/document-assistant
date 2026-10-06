from __future__ import annotations

from dataclasses import dataclass, field


def format_row_id(number: int) -> str:
    """R0001 … R9999, дальше без дополнения нулями.

    Одинаковая ширина помогает модели копировать метку без искажений.
    """
    return f"R{number:04d}"


@dataclass(frozen=True)
class TemplateRow:
    """Строка шаблона, на которую нужен ответ."""

    row_id: str
    sheet: str
    row: int          # 1-based, как в Excel
    text: str         # текст ячейки в столбце требований


@dataclass
class TableLine:
    """Строка таблицы для модели. ``row_id`` пуст у строк-пояснений
    (заголовок таблицы, детализация без текста в столбце требований)."""

    row_id: str | None
    cells: list[str]


@dataclass
class SheetTable:
    sheet: str
    columns: list[str]            # буквы видимых столбцов, например ["D", "E"]
    lines: list[TableLine] = field(default_factory=list)


@dataclass
class ParsedTemplate:
    rows: list[TemplateRow]
    tables: list[SheetTable]

    def by_id(self) -> dict[str, TemplateRow]:
        return {r.row_id: r for r in self.rows}


@dataclass
class RowAnswer:
    row_id: str
    requirement: str   # «Требование (начало)» — эхо текста строки для проверки
    coverage: str
    status: str
    comment: str


@dataclass
class RejectedAnswer:
    answer: RowAnswer
    reason: str
