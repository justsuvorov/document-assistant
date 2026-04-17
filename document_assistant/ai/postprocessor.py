import re

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

    # Matches a markdown table row: | cell | cell | ... |
    _ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
    # Matches a separator row: |---|---| or |:---:|
    _SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)

    def report(self, raw_text: str) -> InsuranceReport:
        if not raw_text:
            return InsuranceReport(raw_text=raw_text)

        rows = self._parse_table(raw_text)
        summary = self._extract_summary(raw_text)

        return InsuranceReport(rows=rows, summary=summary, raw_text=raw_text)

    def _parse_table(self, text: str) -> list[ReportRow]:
        all_row_matches = self._ROW_RE.findall(text)
        if not all_row_matches:
            return []

        result = []
        header_skipped = False

        for raw_row in all_row_matches:
            # Skip separator rows
            if re.fullmatch(r"[\s\-:|]+(\|[\s\-:|]+)*", raw_row.strip()):
                continue

            cells = [c.strip() for c in raw_row.split("|")]

            # Skip the header row (first non-separator row)
            if not header_skipped:
                header_skipped = True
                continue

            # Pad to at least 4 columns
            while len(cells) < 4:
                cells.append("")

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
            if self._ROW_RE.match(line.strip()):
                last_table_line = i

        if last_table_line == -1:
            # No table found — treat the whole response as summary
            return text.strip()

        after = "\n".join(lines[last_table_line + 1:]).strip()
        return after
