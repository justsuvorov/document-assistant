from enum import Enum

from document_assistant.ai.table_parser import MarkdownTableParser


class DeclarationType(str, Enum):
    SINGLE = "single"    # Сценарий 1: одна перевозка
    MULTI = "multi"      # Сценарий 2: мультистрочный документ


class DeclarationTypeClassifier:
    """Determines whether a declaration covers one shipment or many, purely
    from document structure — no LLM call.

    Two-stage heuristic:
    1. Find a genuine item-table header — a row containing "№ п/п" (the
       standard column heading VSK declarations use for a real multi-shipment
       table). Without one, there is no repeating-record structure to speak
       of, so the declaration is SINGLE regardless of how the rest of the
       sheet looks.
    2. Only below that header, count *dense* data rows — rows whose filled-
       cell count is close to the busiest row's — as genuine shipment
       records. 2+ -> MULTI, otherwise SINGLE.

    Why both stages are needed: some single-shipment declarations are laid
    out as a numbered field list ("1. Наименование груза | ...", "2. Род
    упаковки | ...", ... "9. Период страхования | start | по | end") rather
    than a shipment table. A field like "9. Период страхования" can pack as
    many filled cells as a real shipment row purely because it has several
    sub-values (start/end date) — stage 2 alone (density only) mistakes two
    such unrelated field-rows for two shipment records and explodes one
    declaration into dozens of LLM calls. Requiring a "№ п/п" header first
    rules this out: that phrase only appears above a real per-shipment table.
    Stage 2 alone still matters even when a header IS found — it filters out
    the sparse metadata/signature-block rows (policy number, insurer, etc.)
    that share the same sheet.
    """

    # A data row counts as a genuine shipment record only if its filled-cell
    # count is within this fraction of the densest data row in the sheet.
    _DENSITY_RATIO = 0.9
    _ITEM_HEADER_MARKER = "п/п"

    def classify(self, markdown_text: str) -> DeclarationType:
        rows = MarkdownTableParser.parse_rows(markdown_text)
        if len(rows) < 2:
            return DeclarationType.SINGLE

        header_idx = self._find_item_table_header(rows)
        if header_idx is None:
            return DeclarationType.SINGLE

        data_rows = rows[header_idx + 1:]
        if len(data_rows) < 2:
            return DeclarationType.SINGLE

        densities = [sum(1 for cell in row if cell.strip()) for row in data_rows]
        max_density = max(densities)
        if max_density == 0:
            return DeclarationType.SINGLE

        threshold = max_density * self._DENSITY_RATIO
        record_count = sum(1 for d in densities if d >= threshold)
        return DeclarationType.MULTI if record_count >= 2 else DeclarationType.SINGLE

    @classmethod
    def _find_item_table_header(cls, rows: list[list[str]]) -> int | None:
        for i, row in enumerate(rows):
            for cell in row:
                if cls._ITEM_HEADER_MARKER in cell.lower().replace(" ", ""):
                    return i
        return None
