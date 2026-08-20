from enum import Enum

from document_assistant.ai.table_parser import MarkdownTableParser


class DeclarationType(str, Enum):
    SINGLE = "single"    # Сценарий 1: одна перевозка
    MULTI = "multi"      # Сценарий 2: мультистрочный документ


class DeclarationTypeClassifier:
    """Determines whether a declaration covers one shipment or many, purely
    from document structure — no LLM call.

    Heuristic: 2+ *dense* data rows in a markdown table -> MULTI, otherwise
    SINGLE. "Dense" means the row's filled-cell count is close to the busiest
    data row's. This filters out the sparse metadata/label rows real Excel
    declaration exports are full of (policy number, insurer, signature block
    etc. each occupy their own row with only 1-2 filled cells) — without it,
    those noise rows get counted as extra shipments and a single-shipment
    declaration is chunked into one LLM call per noise row.
    """

    # A data row counts as a genuine shipment record only if its filled-cell
    # count is within this fraction of the densest data row in the sheet.
    _DENSITY_RATIO = 0.9

    def classify(self, markdown_text: str) -> DeclarationType:
        rows = MarkdownTableParser.parse_rows(markdown_text)
        data_rows = rows[1:]  # row 0 is the table header
        if len(data_rows) < 2:
            return DeclarationType.SINGLE

        densities = [sum(1 for cell in row if cell.strip()) for row in data_rows]
        max_density = max(densities)
        if max_density == 0:
            return DeclarationType.SINGLE

        threshold = max_density * self._DENSITY_RATIO
        record_count = sum(1 for d in densities if d >= threshold)
        return DeclarationType.MULTI if record_count >= 2 else DeclarationType.SINGLE
