from enum import Enum

from document_assistant.cargo.shipment_table import find_shipment_rows


class DeclarationType(str, Enum):
    SINGLE = "single"    # Сценарий 1: одна перевозка (вертикальная форма)
    MULTI = "multi"      # Сценарий 2: мультистрочный документ (горизонтальная, ПСГ)


class DeclarationTypeClassifier:
    """Determines whether a declaration covers one shipment or many, purely
    from document structure — no LLM call.

    A declaration is MULTI when it contains a «№ п/п» shipment table with at
    least two sequence-numbered rows. Both conditions matter:

    - The «№ п/п» header must be a real column header (several named
      columns), not a stray «№ п/п договора» label in a vertical field list.
    - The rows counted must actually be numbered 1, 2, 3… in that column.
      Counting "dense-looking" rows instead pulled in the title, the
      Страхователь/Страховщик metadata block and the signature lines, which
      is how a two-shipment declaration turned into fifteen chunks.

    The row-finding itself lives in shipment_table so that classification and
    chunking can never disagree about what a shipment row is.
    """

    def classify(self, markdown_text: str) -> DeclarationType:
        _, shipment_rows = find_shipment_rows(markdown_text)
        return DeclarationType.MULTI if len(shipment_rows) >= 2 else DeclarationType.SINGLE
