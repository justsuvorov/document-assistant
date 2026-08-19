from datetime import date
from pathlib import Path

from document_assistant.cargo.declaration_numbering import DeclarationNumbering
from document_assistant.core.settings import settings


class ReconciliationOutputResolver:
    """Resolves where the result file for one declaration is written: a
    sibling of the source declaration file, matching ReportExport's
    ``{stem}_ответ{ext}`` convention for the DMS pipeline.
    """

    @staticmethod
    def resolve(declaration_path: str, declaration_number: str) -> Path:
        src = Path(declaration_path)
        return src.parent / DeclarationNumbering.output_filename(declaration_number)


class PeriodMonthResolver:
    """Non-destructive check of the "Декларации/{месяц}/" business rule: warns
    when a declaration doesn't live in the month folder that its insurance
    period start date implies. Never moves or creates files.
    """

    @staticmethod
    def expected_month_folder(period_start: date) -> str:
        return period_start.strftime(settings.declarations_month_format)

    @staticmethod
    def warn_if_mismatched(declaration_path: str, period_start: date | None) -> str | None:
        if period_start is None:
            return None
        expected = PeriodMonthResolver.expected_month_folder(period_start)
        actual = Path(declaration_path).parent.name
        if actual != expected:
            return (
                f"Файл лежит в папке '{actual}', ожидалась '{expected}' "
                f"по дате начала периода страхования"
            )
        return None
