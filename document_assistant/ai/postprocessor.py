import re

from document_assistant.ai.table_parser import MarkdownTableParser
from document_assistant.reports.report_models import InsuranceReport, ReportRow


class PostProcessor:
    """Parse the raw LLM markdown response into a structured InsuranceReport.

    Expected LLM output format:
        ...optional text...
        | Требование клиента | Покрытие по программе | Статус | Комментарий |
        |---|---|---|---|
        | row 1 ... |
        ...
        ...summary text after the table...
    """

    def report(self, raw_text: str, chunk_index: int | None = None) -> InsuranceReport:
        if not raw_text:
            return InsuranceReport(raw_text=raw_text)

        rows = self._parse_table(raw_text)
        summary = self._extract_summary(raw_text)

        return InsuranceReport(rows=rows, summary=summary, raw_text=raw_text)

    _SUMMARY_RE = re.compile(r"^#{1,3}\s*(Резюме|Вывод|Summary)", re.MULTILINE | re.IGNORECASE)

    def _parse_table(self, text: str) -> list[ReportRow]:
        # Truncate at résumé heading so its tables are not parsed as data rows
        summary_match = self._SUMMARY_RE.search(text)
        if summary_match:
            text = text[:summary_match.start()]

        parsed_rows = MarkdownTableParser.parse_rows(text, min_columns=4)
        if not parsed_rows:
            return []

        result = []
        for cells in parsed_rows[1:]:  # skip the header row (first non-separator row)
            result.append(ReportRow(
                client_requirement=cells[0],
                program_coverage=cells[1],
                status=cells[2],
                comment=cells[3],
            ))

        return result

    def _extract_summary(self, text: str) -> str:
        """Return the text block that comes after the last table row."""
        lines = text.splitlines()
        last_table_line = -1

        for i, line in enumerate(lines):
            if MarkdownTableParser.ROW_RE.match(line.strip()):
                last_table_line = i

        if last_table_line == -1:
            # No table found — treat the whole response as summary
            return text.strip()

        after = "\n".join(lines[last_table_line + 1:]).strip()
        return after
