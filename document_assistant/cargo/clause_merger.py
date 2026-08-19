import re

from document_assistant.cargo.matrix_postprocessor import RawClause
from document_assistant.cargo.models import PolicyClause, PolicySource


class ClauseMerger:
    """Merges per-document clause candidates into one currently-effective matrix.

    Pure function of (source, candidates) pairs — no LLM call, no I/O — so the
    "latest ДС wins" precedence rule is fully unit-testable. Callers must pass
    sources in ASCENDING precedence order (policy first, then ДС ascending by
    number — see PolicySource.sort_key/PolicyFolderScanner.scan): a later
    entry for the same clause always overwrites an earlier one.

    Clause identity across documents is matched two ways:
    1. By CLAUSE NUMBER — the leading number in the LLM's "Пункт" text (e.g.
       "9. Объект страхования" -> "9"). This is the primary, reliable key:
       a ДС's file name already tells us which clause numbers it amends
       (see PolicyFilenameParser.parse_ds), and the LLM is prompted to name
       the clause number it extracted, so both sides of the merge agree on
       the same number space.
    2. Fuzzy text match (same tiering as ExcelReportWriter._find_row_global:
       exact normalized -> prefix -> word-overlap >= 75%) as a fallback for
       candidates where no clause number could be parsed.
    """

    _LEADING_NUMBER_RE = re.compile(r"^\s*(?:п\.?\s*)?(\d+(?:\.\d+)*)\b")

    def merge(self, sources_with_candidates: list[tuple[PolicySource, list[RawClause]]]) -> list[PolicyClause]:
        merged: list[PolicyClause] = []
        index_by_number: dict[str, int] = {}
        index_by_text: dict[str, int] = {}

        for source, candidates in sources_with_candidates:
            for raw in candidates:
                text_key = self._normalize(raw.clause_id)
                if not text_key:
                    continue
                number_key = self._clause_number(raw.clause_id)

                if number_key is not None:
                    # A parsed number is authoritative identity — a number
                    # not seen before means a genuinely new clause. Do NOT
                    # fall back to fuzzy text matching here: two differently
                    # numbered clauses can share title words (word-overlap
                    # ignores numbers, since digits are filtered as
                    # too-short tokens) and would otherwise get wrongly
                    # merged into one.
                    position = index_by_number.get(number_key)
                else:
                    position = self._find_text_match(text_key, index_by_text)

                clause = PolicyClause(
                    clause_id=raw.clause_id,
                    clause_title="",
                    effective_text=raw.effective_text,
                    source_label=source.label,
                    source_file=source.file_path,
                )

                if position is None:
                    merged.append(clause)
                    position = len(merged) - 1
                else:
                    merged[position] = clause

                if number_key:
                    index_by_number[number_key] = position
                index_by_text[text_key] = position

        return merged

    @classmethod
    def _clause_number(cls, text: str) -> str | None:
        match = cls._LEADING_NUMBER_RE.match(text)
        return match.group(1) if match else None

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _words(text: str) -> set[str]:
        return {w for w in re.split(r"\W+", text.lower()) if len(w) > 2}

    def _find_text_match(self, key: str, index: dict[str, int]) -> int | None:
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
