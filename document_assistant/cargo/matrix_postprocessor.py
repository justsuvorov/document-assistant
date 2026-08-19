from dataclasses import dataclass, field

from document_assistant.ai.table_parser import MarkdownTableParser


@dataclass
class RawClause:
    """One clause candidate extracted from a single policy/ДС document.

    Not yet a PolicyClause: source/effective_from/priority are filled in by
    RulesMatrixBuilder from the owning PolicySource, not by the LLM.
    """
    clause_id: str
    effective_text: str
    comment: str = ""


@dataclass
class CandidateBatch:
    """The 'report' produced per chunk when AIAssistantService runs clause
    extraction for one policy/ДС document — just a list of RawClause plus the
    raw_text AIAssistantService's debug logging expects (.rows/.raw_text
    mirror InsuranceReport's shape so the same orchestrator works unmodified).
    """
    rows: list[RawClause] = field(default_factory=list)
    raw_text: str = ""

    @classmethod
    def merge(cls, batches: list["CandidateBatch"]) -> "CandidateBatch":
        rows = [r for b in batches for r in b.rows]
        raw_text = "\n\n---\n\n".join(b.raw_text for b in batches if b.raw_text)
        return cls(rows=rows, raw_text=raw_text)


class MatrixPostProcessor:
    """Parse the LLM's clause-extraction response for a single policy/ДС document.

    Expected format:
        | Пункт (номер/название) | Актуальный текст/значение | Комментарий |
        |---|---|---|
        | ... | ... | ... |
    """

    def parse(self, raw_text: str) -> list[RawClause]:
        if not raw_text:
            return []

        parsed_rows = MarkdownTableParser.parse_rows(raw_text, min_columns=3)
        if not parsed_rows:
            return []

        result = []
        for cells in parsed_rows[1:]:  # skip header row
            clause_id = cells[0].strip()
            if not clause_id:
                continue
            result.append(RawClause(
                clause_id=clause_id,
                effective_text=cells[1].strip(),
                comment=cells[2].strip() if len(cells) > 2 else "",
            ))
        return result

    def report(self, raw_text: str, chunk_index: int | None = None) -> CandidateBatch:
        """Adapter so this postprocessor can plug into AIAssistantService
        (which calls .report(raw_text, chunk_index), not .parse(raw_text))."""
        return CandidateBatch(rows=self.parse(raw_text), raw_text=raw_text)
