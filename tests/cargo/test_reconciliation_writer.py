from pathlib import Path

from openpyxl import load_workbook

from document_assistant.cargo.models import ReconciliationReport, ReconciliationRow
from document_assistant.cargo.reconciliation_writer import ReconciliationExcelWriter
from document_assistant.reports.writers import ReportWriter

TEMPLATE_PATH = Path(__file__).parents[2] / "document_assistant" / "cargo" / "templates" / "reconciliation_form.xlsx"


def _sample_report() -> ReconciliationReport:
    return ReconciliationReport(
        declaration_number="200",
        rows=[
            ReconciliationRow("200/1", "Объект страхования", "3.2", "совпадает", "Полное совпадение"),
            ReconciliationRow("200/1", "Маршрут", "4.1", "не совпадает", "Выходит за территорию"),
            ReconciliationRow("200/2", "Объект страхования", "3.2", "не знаю", "Пункт не найден"),
        ],
    )


class TestReconciliationExcelWriter:
    def test_extends_shared_report_writer_abc(self):
        assert isinstance(ReconciliationExcelWriter(), ReportWriter)

    def test_writes_using_repo_template(self, tmp_path: Path):
        assert TEMPLATE_PATH.exists(), "Response template must be copied into the repo"
        writer = ReconciliationExcelWriter(template_path=str(TEMPLATE_PATH))
        output_path = tmp_path / "200 – результат проверки.xlsx"

        writer.write(_sample_report(), output_path)

        assert output_path.exists()
        wb = load_workbook(output_path)
        ws = wb.active

        headers = [ws.cell(row=1, column=c).value for c in range(1, 6)]
        assert headers[0] == "Номер декларации/строки"
        assert "совпадает" in headers[3]

    def test_writes_all_rows(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(template_path=str(TEMPLATE_PATH))
        output_path = tmp_path / "200 – результат проверки.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        ws = wb.active
        assert ws.cell(row=2, column=1).value == "200/1"
        assert ws.cell(row=2, column=2).value == "Объект страхования"
        assert ws.cell(row=4, column=1).value == "200/2"

    def test_column_widths_autofit_to_content(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(template_path=str(TEMPLATE_PATH))
        output_path = tmp_path / "out.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        ws = wb.active
        # Column A's longest content is the header itself ("Номер декларации/строки", 24 chars)
        assert ws.column_dimensions["A"].width == len("Номер декларации/строки") + 2

    def test_header_row_is_frozen(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(template_path=str(TEMPLATE_PATH))
        output_path = tmp_path / "out.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        ws = wb.active
        assert ws.freeze_panes == "A2"

    def test_special_conditions_sheet_added_when_present(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(
            template_path=str(TEMPLATE_PATH), special_conditions_text="Особый порядок уведомления",
        )
        output_path = tmp_path / "out.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        assert "Особые условия" in wb.sheetnames

    def test_no_special_conditions_sheet_when_empty(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(template_path=str(TEMPLATE_PATH), special_conditions_text="")
        output_path = tmp_path / "out.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        assert "Особые условия" not in wb.sheetnames

    def test_falls_back_to_fresh_workbook_without_template(self, tmp_path: Path):
        writer = ReconciliationExcelWriter(template_path="")
        output_path = tmp_path / "out.xlsx"

        writer.write(_sample_report(), output_path)

        wb = load_workbook(output_path)
        ws = wb.active
        assert ws.cell(row=1, column=1).value == "Номер декларации/строки"
        assert ws.cell(row=2, column=1).value == "200/1"
