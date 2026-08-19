from enum import Enum

from document_assistant.ai.table_parser import MarkdownTableParser


class DeclarationType(str, Enum):
    SINGLE = "single"    # Сценарий 1: одна перевозка
    MULTI = "multi"      # Сценарий 2: мультистрочный документ


class DeclarationTypeClassifier:
    """Determines whether a declaration covers one shipment or many, purely
    from document structure — no LLM call.

    Heuristic: 2+ data rows in a markdown table -> MULTI, otherwise SINGLE
    (a lone table row, or free-form prose with no table, is treated as a
    single-shipment declaration).
    """

    def classify(self, markdown_text: str) -> DeclarationType:
        data_rows = MarkdownTableParser.count_data_rows(markdown_text)
        return DeclarationType.MULTI if data_rows >= 2 else DeclarationType.SINGLE
