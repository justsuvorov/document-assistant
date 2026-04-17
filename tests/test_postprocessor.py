import pytest
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.reports.report_models import InsuranceReport


SAMPLE_RESPONSE = """\
Выбрана программа страхования «Имущество Плюс».

| Требование клиента | Покрытие по программе | Статус | Комментарий |
|---|---|---|---|
| Пожар | Полное покрытие | Есть | Лимит 5 000 000 руб. |
| Затопление | Частичное покрытие | Частично | Только от прорыва труб |
| Землетрясение | Не покрывается | Нет | Требуется доп. полис |

## Резюме
Программа покрывает 2 из 3 требований клиента.
"""


class TestPostProcessor:
    def setup_method(self):
        self.pp = PostProcessor()

    def test_returns_insurance_report(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert isinstance(result, InsuranceReport)

    def test_parses_all_rows(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert len(result.rows) == 3

    def test_row_fields(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        first = result.rows[0]
        assert first.client_requirement == "Пожар"
        assert first.program_coverage == "Полное покрытие"
        assert first.status == "Есть"
        assert "5 000 000" in first.comment

    def test_status_values(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        statuses = [r.status for r in result.rows]
        assert statuses == ["Есть", "Частично", "Нет"]

    def test_summary_extracted(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert "Резюме" in result.summary or "2 из 3" in result.summary

    def test_raw_text_preserved(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert result.raw_text == SAMPLE_RESPONSE

    def test_empty_input(self):
        result = self.pp.report("")
        assert isinstance(result, InsuranceReport)
        assert result.rows == []
        assert result.summary == ""

    def test_no_table_summary_is_full_text(self):
        text = "Программа не найдена. Требуется ручная обработка."
        result = self.pp.report(text)
        assert result.rows == []
        assert result.summary == text

    def test_incomplete_row_padded(self):
        response = (
            "| Требование | Покрытие | Статус | Комментарий |\n"
            "|---|---|---|---|\n"
            "| Риск А | Есть |\n"  # only 2 cells
        )
        result = self.pp.report(response)
        assert len(result.rows) == 1
        assert result.rows[0].status == ""
