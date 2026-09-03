from document_assistant.ai.preprocessor import Preprocessor
from document_assistant.cargo.preprocessors import ClauseExtractionPreprocessor, DeclarationPreprocessor


class FakeReconciliationPromptEngine:
    def build(self, rules_matrix_block, special_conditions, source_text,
              template_fields_block="", carrier_list_text=""):
        extras = ""
        if template_fields_block:
            extras += f"|fields:{template_fields_block}"
        if carrier_list_text:
            extras += f"|carriers:{carrier_list_text}"
        return f"[{rules_matrix_block}|{special_conditions}|{source_text}{extras}]"


class FakeMatrixPromptEngine:
    def build(self, source_text, clause_numbers=None):
        suffix = f"|clauses:{','.join(clause_numbers)}" if clause_numbers else ""
        return f"[matrix:{source_text}{suffix}]"


class TestDeclarationPreprocessor:
    def test_extends_preprocessor_base(self):
        pp = DeclarationPreprocessor([], FakeReconciliationPromptEngine(), "", "")
        assert isinstance(pp, Preprocessor)

    def test_builds_one_prompt_per_chunk(self):
        pp = DeclarationPreprocessor(
            chunks=["row1", "row2", "row3"],
            prompt_engine=FakeReconciliationPromptEngine(),
            rules_matrix_block="MATRIX",
            special_conditions_text="COND",
        )
        queries = pp.queries()
        assert len(queries) == 3
        assert queries[0] == "[MATRIX|COND|row1]"
        assert queries[2] == "[MATRIX|COND|row3]"

    def test_empty_chunks_yields_no_queries(self):
        pp = DeclarationPreprocessor([], FakeReconciliationPromptEngine(), "MATRIX", "COND")
        assert pp.queries() == []

    def test_template_fields_and_carriers_forwarded(self):
        pp = DeclarationPreprocessor(
            chunks=["row1"],
            prompt_engine=FakeReconciliationPromptEngine(),
            rules_matrix_block="MATRIX",
            special_conditions_text="COND",
            template_fields_block="FIELDS",
            carrier_list_text="CARRIERS",
        )
        query = pp.queries()[0]
        assert "fields:FIELDS" in query
        assert "carriers:CARRIERS" in query


class TestClauseExtractionPreprocessor:
    def test_extends_preprocessor_base(self):
        pp = ClauseExtractionPreprocessor([], FakeMatrixPromptEngine())
        assert isinstance(pp, Preprocessor)

    def test_builds_one_prompt_per_chunk(self):
        pp = ClauseExtractionPreprocessor(["chunk1", "chunk2"], FakeMatrixPromptEngine())
        queries = pp.queries()
        assert queries == ["[matrix:chunk1]", "[matrix:chunk2]"]

    def test_passes_clause_numbers_through(self):
        pp = ClauseExtractionPreprocessor(["chunk1"], FakeMatrixPromptEngine(), clause_numbers=["9", "7"])
        queries = pp.queries()
        assert queries == ["[matrix:chunk1|clauses:9,7]"]
