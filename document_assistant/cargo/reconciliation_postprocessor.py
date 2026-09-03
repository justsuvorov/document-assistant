from document_assistant.ai.table_parser import MarkdownTableParser
from document_assistant.cargo import result_consistency
from document_assistant.cargo.declaration_numbering import DeclarationNumbering
from document_assistant.cargo.models import ReconciliationReport, ReconciliationRow


class ReconciliationPostProcessor:
    """Parses the LLM's field-by-field reconciliation response for ONE
    declaration file — one instance is reused across all of that
    declaration's chunk calls inside AIAssistantService.result().

    Expected format:
        | Наименование поля в декларации | С каким пунктом Ген. полиса сверено | Результат проверки | Комментарий по сверке |
        |---|---|---|---|
        | ... | ... | совпадает/не совпадает/не знаю | ... |

    declaration_number is fixed at construction (parsed from the file name
    before AIAssistantService runs). The row label ("200" vs "200/1") is
    derived from the chunk_index AIAssistantService passes into .report() —
    not an internal counter — so it stays correct even if an earlier chunk
    fails all retries and is skipped.
    """

    def __init__(self, declaration_number: str, multi: bool):
        self._declaration_number = declaration_number
        self._multi = multi

    def report(self, raw_text: str, chunk_index: int | None = None) -> ReconciliationReport:
        if not raw_text:
            return ReconciliationReport(declaration_number=self._declaration_number, raw_text=raw_text)

        line_idx = chunk_index if self._multi else None
        ref = DeclarationNumbering.row_label(self._declaration_number, line_idx)

        parsed_rows = MarkdownTableParser.parse_rows(raw_text, min_columns=4)
        rows = [
            ReconciliationRow(
                declaration_ref=ref,
                field_name=cells[0],
                matched_policy_clause=cells[1],
                result=cells[2],
                comment=cells[3],
            )
            for cells in parsed_rows[1:]  # skip header row
        ]
        result_consistency.apply(rows, ref)

        return ReconciliationReport(declaration_number=self._declaration_number, rows=rows, raw_text=raw_text)
