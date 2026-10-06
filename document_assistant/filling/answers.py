"""Разбор ответа модели по ID и проверка каждой строки перед записью."""

from __future__ import annotations

import re

from document_assistant.filling.models import (
    RejectedAnswer,
    RowAnswer,
    TemplateRow,
    format_row_id,
)
from document_assistant.reports.writers import ExcelReportWriter

_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_ID_RE = re.compile(r"^\**\s*R\s*0*(\d+)\s*\**$", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"^#{1,3}\s*(Резюме|Вывод|Summary)", re.MULTILINE | re.IGNORECASE)
_ELLIPSIS_TAIL = re.compile(r"[\s;,:.]*(?:\.\.\.|…)\s*$")


class AnswerParser:
    """Таблица ``| ID | Требование (начало) | Покрытие | Статус | Комментарий |``.

    Строки без распознаваемого ID в первой ячейке (шапка, разделитель,
    случайные таблицы) пропускаются. Если модель выкинула столбец
    «Требование», строка из 4 ячеек тоже принимается — с пустым текстом.
    """

    def parse(self, raw: str) -> tuple[list[RowAnswer], str]:
        if not raw:
            return [], ""
        summary = ""
        table_part = raw
        m = _SUMMARY_RE.search(raw)
        if m:
            table_part, summary = raw[:m.start()], raw[m.end():].strip()

        answers: list[RowAnswer] = []
        for line in table_part.splitlines():
            row = _ROW_RE.match(line)
            if not row:
                continue
            cells = [c.strip() for c in row.group(1).split("|")]
            id_match = _ID_RE.match(cells[0]) if cells else None
            if not id_match:
                continue
            row_id = format_row_id(int(id_match.group(1)))
            rest = cells[1:]
            if len(rest) == 3:
                rest = [""] + rest
            rest += [""] * (4 - len(rest))
            # Лишние ячейки (модель разбила комментарий по «|») склеиваем обратно.
            comment = " | ".join(c for c in rest[3:] if c)
            answers.append(RowAnswer(row_id, rest[0], rest[1], rest[2], comment))
        return answers, summary


def _stem_list(text: str) -> list[str]:
    """Значимые токены: первые 5 букв слов длиннее 2 символов и все числа.

    Обрезка до 5 букв гасит окончания («остеопата» / «остеопат»). Числа
    оставлены целиком: «диабет 1 типа» и «диабет 2 типа» — разные строки.
    """
    return [w if w.isdigit() else w[:5]
            for w in re.split(r"\W+", text.lower()) if w.isdigit() or len(w) > 2]


_MIN_ECHO_WORDS = 8


def _starts_at_word(text: str, prefix: str) -> bool:
    """``text`` начинается с ``prefix`` по границе слова: «хирург» — не начало
    «хирургического»."""
    return text.startswith(prefix) and (len(text) == len(prefix) or not text[len(prefix)].isalnum())


def text_agrees(model_text: str, template_text: str) -> bool:
    """Совпадает ли эхо модели с текстом строки шаблона.

    Строго по смыслу «это та же строка», но терпимо к сокращению, «…»,
    маркерам списка, регистру и окончаниям. Пустое эхо — не повод
    отбрасывать: ID уже указывает на строку, а проверять нечего.
    """
    m = ExcelReportWriter._norm(model_text)
    while _ELLIPSIS_TAIL.search(m):
        m = _ELLIPSIS_TAIL.sub("", m)
    if not m:
        return True
    t = ExcelReportWriter._norm(template_text)
    if m == t:
        return True
    # Модель дописала к тексту детализацию («Анализ крови / клинический»).
    if _starts_at_word(m, t):
        return True
    # Модель привела начало текста. Короткое эхо обязано быть всем текстом:
    # иначе заголовок «САХАРНЫЙ ДИАБЕТ» сошёл бы за начало соседней строки
    # «Сахарный диабет 1 тип…».
    if _starts_at_word(t, m) and len(m.split()) >= _MIN_ECHO_WORDS:
        return True
    model_stems = _stem_list(m)
    # С эхом сравниваем такой же по длине кусок начала строки шаблона: иначе
    # короткое эхо «САХАРНЫЙ ДИАБЕТ» целиком нашлось бы в «Сахарный диабет 1 тип…».
    tmpl_stems = _stem_list(t)[:len(model_stems) + 1]
    if not model_stems or not tmpl_stems:
        return False
    # Соседние строки шаблона часто различаются только началом при общем
    # хвосте («водолечение … в лечебных целях» / «грязелечение … в лечебных
    # целях»), поэтому первое значимое слово обязано совпасть.
    if model_stems[0] != tmpl_stems[0]:
        return False
    if {x for x in model_stems if x.isdigit()} != {x for x in tmpl_stems if x.isdigit()}:
        return False
    common = set(model_stems) & set(tmpl_stems)
    return len(common) / max(len(set(model_stems)), len(set(tmpl_stems))) >= 0.8


class AnswerValidator:
    """Принимает ответ, только если можно быть уверенным, куда он относится.

    Отбрасывается (строка остаётся без ответа — «Не обработано»):
      - ID, которого нет в этой части запроса;
      - повтор ID (берётся первый ответ);
      - эхо требования, явно не совпадающее с текстом строки шаблона.
    """

    def __init__(self, rows: dict[str, TemplateRow]):
        self._rows = rows
        self.accepted: dict[str, RowAnswer] = {}
        self.rejected: list[RejectedAnswer] = []

    def add(self, answers: list[RowAnswer], allowed_ids: set[str]) -> tuple[int, int]:
        """Вернуть (принято, отброшено) для этой порции ответов."""
        ok = bad = 0
        for a in answers:
            reason = self._reject_reason(a, allowed_ids)
            if reason:
                self.rejected.append(RejectedAnswer(a, reason))
                bad += 1
            else:
                self.accepted[a.row_id] = a
                ok += 1
        return ok, bad

    def _reject_reason(self, a: RowAnswer, allowed_ids: set[str]) -> str | None:
        if a.row_id not in allowed_ids:
            return "ID не из этой части запроса"
        if a.row_id in self.accepted:
            return "повтор ID"
        if not text_agrees(a.requirement, self._rows[a.row_id].text):
            return "текст не совпадает со строкой шаблона"
        return None
