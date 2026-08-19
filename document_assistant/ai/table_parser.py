import re


class MarkdownTableParser:
    """Shared markdown-table regexes and row extraction.

    Used by ``PostProcessor`` (LLM response parsing), ``DocumentChunker``
    (table-row batching) and the cargo reconciliation postprocessors — one
    source of truth instead of three copies of the same regex.
    """

    ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)
    SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)
    TABLE_ROW = re.compile(r"^\|.+\|$")
    TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|$")

    @classmethod
    def is_separator_row(cls, raw_row: str) -> bool:
        return bool(re.fullmatch(r"[\s\-:|]+(\|[\s\-:|]+)*", raw_row.strip()))

    @classmethod
    def split_cells(cls, raw_row: str) -> list[str]:
        return [c.strip() for c in raw_row.split("|")]

    @classmethod
    def parse_rows(cls, text: str, min_columns: int = 0) -> list[list[str]]:
        """Return all non-separator table rows in ``text`` as lists of cells.

        The first non-separator row (the header) is included — callers that
        want data rows only should skip index 0.
        """
        rows: list[list[str]] = []
        for raw_row in cls.ROW_RE.findall(text):
            if cls.is_separator_row(raw_row):
                continue
            cells = cls.split_cells(raw_row)
            while len(cells) < min_columns:
                cells.append("")
            rows.append(cells)
        return rows

    @classmethod
    def count_data_rows(cls, text: str) -> int:
        """Count table data rows (rows after the header+separator) across the text."""
        lines = text.splitlines()
        header_idx = sep_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if cls.TABLE_ROW.match(stripped) and header_idx is None:
                header_idx = i
            elif header_idx is not None and cls.TABLE_SEP.match(stripped):
                sep_idx = i
                break
        if header_idx is None or sep_idx is None:
            return 0
        return sum(1 for line in lines[sep_idx + 1:] if cls.TABLE_ROW.match(line.strip()))
