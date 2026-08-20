from document_assistant.cargo.clause_merger import ClauseMerger
from document_assistant.cargo.matrix_postprocessor import RawClause
from document_assistant.cargo.models import PolicySource


class TestClauseMerger:
    def setup_method(self):
        self.merger = ClauseMerger()

    def test_single_source_no_conflict(self):
        policy = PolicySource(kind="policy", file_path="policy.docx")
        candidates = [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование")]

        result = self.merger.merge([(policy, candidates)])

        assert len(result) == 1
        assert result[0].effective_text == "Оборудование"
        assert result[0].source_label == "Ген. полис"

    def test_later_ds_overrides_earlier_ds_by_clause_number(self):
        """The clause originates in the policy (as "9. ..."), gets amended by
        ДС 1 (п.9), then amended AGAIN by ДС 2 (п.9) — the latest (ДС 2) text
        must win, matched by CLAUSE NUMBER, per the ТЗ's core business rule.
        """
        policy = PolicySource(kind="policy", file_path="policy.docx")
        ds1 = PolicySource(kind="ds", file_path="ds1.docx", ds_number=1, clause_numbers=["9"])
        ds2 = PolicySource(kind="ds", file_path="ds2.docx", ds_number=2, clause_numbers=["9"])

        sources_with_candidates = [
            (policy, [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование")]),
            (ds1, [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование и запчасти")]),
            (ds2, [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование, запчасти и материалы")]),
        ]

        result = self.merger.merge(sources_with_candidates)

        assert len(result) == 1  # same clause number, not three separate entries
        assert result[0].effective_text == "Оборудование, запчасти и материалы"
        assert "2" in result[0].source_label

    def test_clause_number_match_ignores_differing_title_text(self):
        """Real ДС extractions rarely repeat the exact clause title — matching
        by the LEADING NUMBER (not the fuzzy title) must still merge them."""
        policy = PolicySource(kind="policy", file_path="policy.docx")
        ds1 = PolicySource(kind="ds", file_path="ds1.docx", ds_number=1, clause_numbers=["9"])

        result = self.merger.merge([
            (policy, [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование")]),
            (ds1, [RawClause(clause_id="9. Объект и груз страхования (уточнено)", effective_text="Оборудование и запчасти")]),
        ])

        assert len(result) == 1
        assert result[0].effective_text == "Оборудование и запчасти"

    def test_processing_order_determines_winner(self):
        """merge() trusts caller ordering (ascending precedence) — if callers
        pass sources out of order, the LAST one processed wins. This test
        documents that contract rather than re-deriving precedence itself.
        """
        ds_early = PolicySource(kind="ds", file_path="a.docx", ds_number=5, clause_numbers=["4"])
        ds_late = PolicySource(kind="ds", file_path="b.docx", ds_number=1, clause_numbers=["4"])

        result = self.merger.merge([
            (ds_early, [RawClause(clause_id="4. Лимит", effective_text="1 000 000")]),
            (ds_late, [RawClause(clause_id="4. Лимит", effective_text="2 000 000")]),
        ])

        assert len(result) == 1
        assert result[0].effective_text == "2 000 000"

    def test_unrelated_clauses_stay_separate(self):
        policy = PolicySource(kind="policy", file_path="policy.docx")
        ds1 = PolicySource(kind="ds", file_path="ds1.docx", ds_number=1, clause_numbers=["5"])

        result = self.merger.merge([
            (policy, [RawClause(clause_id="9. Объект страхования", effective_text="Оборудование")]),
            (ds1, [RawClause(clause_id="5. Франшиза", effective_text="10000 руб.")]),
        ])

        assert len(result) == 2

    def test_fuzzy_text_fallback_when_no_leading_number(self):
        """Candidates without a parseable leading number fall back to the
        original fuzzy text matching (prefix tier here)."""
        policy = PolicySource(kind="policy", file_path="policy.docx")
        ds1 = PolicySource(kind="ds", file_path="ds1.docx", ds_number=1)

        result = self.merger.merge([
            (policy, [RawClause(clause_id="Объект страхования", effective_text="Оборудование")]),
            (ds1, [RawClause(clause_id="Объект страхования по договору", effective_text="Оборудование и запчасти")]),
        ])

        assert len(result) == 1
        assert result[0].effective_text == "Оборудование и запчасти"
