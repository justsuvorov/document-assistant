import re

from document_assistant.cargo.matrix_postprocessor import RawClause
from document_assistant.cargo.models import PolicyClause, PolicySource


class ClauseMerger:
    """Merges per-document clause candidates into one currently-effective matrix.

    Pure function of (source, candidates) pairs — no LLM call, no I/O — so the
    "latest ДС wins" precedence rule is fully unit-testable. Callers must pass
    sources in ASCENDING precedence order (policy first, then ДС oldest to
    newest — see PolicySource.sort_key/PolicyFolderScanner.scan): a later
    entry for the same clause always overwrites an earlier one.

    Clause identity across documents is fuzzy-matched (same tiering as
    ExcelReportWriter._find_row_global): exact normalized match, then
    prefix, then word-overlap >= 75%.
    """

    def merge(self, sources_with_candidates: list[tuple[PolicySource, list[RawClause]]]) -> list[PolicyClause]:
        merged: list[PolicyClause] = []
        index: dict[str, int] = {}  # normalized clause_id -> index into merged

        for source, candidates in sources_with_candidates:
            for raw in candidates:
                key = self._normalize(raw.clause_id)
                if not key:
                    continue
                position = self._find_match(key, index)
                clause = PolicyClause(
                    clause_id=raw.clause_id,
                    clause_title="",
                    effective_text=raw.effective_text,
                    source_label=source.label,
                    source_file=source.file_path,
                    effective_from=source.valid_from,
                )
                if position is None:
                    merged.append(clause)
                    index[key] = len(merged) - 1
                else:
                    merged[position] = clause
                    index[key] = position

        return merged

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _words(text: str) -> set[str]:
        return {w for w in re.split(r"\W+", text.lower()) if len(w) > 2}

    def _find_match(self, key: str, index: dict[str, int]) -> int | None:
        if key in index:
            return index[key]

        for existing_key, pos in index.items():
            shorter, longer = sorted((len(existing_key), len(key)))
            if shorter >= 4 and (existing_key.startswith(key) or key.startswith(existing_key)):
                return pos

        key_words = self._words(key)
        if len(key_words) < 2:
            return None
        best_score, best_pos = 0.0, None
        for existing_key, pos in index.items():
            existing_words = self._words(existing_key)
            if not existing_words:
                continue
            shorter = min(len(key_words), len(existing_words))
            longer = max(len(key_words), len(existing_words))
            if longer > 3 * shorter:
                continue
            overlap = len(key_words & existing_words) / shorter
            if overlap > best_score:
                best_score, best_pos = overlap, pos
        return best_pos if best_score >= 0.75 else None
