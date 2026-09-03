from document_assistant.cargo.reconciliation_postprocessor import ReconciliationPostProcessor

SAMPLE_RESPONSE = """\
| Наименование поля в декларации | С каким пунктом Ген. полиса сверено | Результат проверки | Комментарий по сверке |
|---|---|---|---|
| Объект страхования | 3.2 Объект страхования | совпадает | Полное совпадение |
| Маршрут | 4.1 Территория страхования | не совпадает | Маршрут выходит за пределы территории |
| Стоимость груза | — | не знаю | Пункт не найден в матрице |
"""


class TestSingleDeclaration:
    """multi=False — declaration_ref never gets a line suffix, regardless of chunk_index."""

    def setup_method(self):
        self.pp = ReconciliationPostProcessor(declaration_number="200", multi=False)

    def test_parses_all_rows(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert len(result.rows) == 3

    def test_declaration_number_set(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        assert result.declaration_number == "200"
        assert all(row.declaration_ref == "200" for row in result.rows)

    def test_declaration_ref_ignores_chunk_index_when_not_multi(self):
        result = self.pp.report(SAMPLE_RESPONSE, chunk_index=1)
        assert all(row.declaration_ref == "200" for row in result.rows)

    def test_fields(self):
        result = self.pp.report(SAMPLE_RESPONSE)
        first = result.rows[0]
        assert first.field_name == "Объект страхования"
        assert first.matched_policy_clause == "3.2 Объект страхования"
        assert first.result == "совпадает"
        assert first.comment == "Полное совпадение"

    def test_result_values_normalized_to_two_allowed_values(self):
        """The response form allows only «совпадает»/«не совпадает» — anything
        else the model returns (here «не знаю») collapses to «не совпадает»."""
        result = self.pp.report(SAMPLE_RESPONSE)
        assert [row.result for row in result.rows] == ["совпадает", "не совпадает", "не совпадает"]

    def test_empty_input(self):
        result = self.pp.report("")
        assert result.rows == []
        assert result.declaration_number == "200"


class TestMultiRowDeclaration:
    """multi=True — declaration_ref carries the chunk_index AIAssistantService passes in,
    not an internal counter, so a skipped/failed earlier chunk doesn't shift later labels."""

    def setup_method(self):
        self.pp = ReconciliationPostProcessor(declaration_number="200", multi=True)

    def test_declaration_ref_uses_chunk_index(self):
        result = self.pp.report(SAMPLE_RESPONSE, chunk_index=2)
        assert all(row.declaration_ref == "200/2" for row in result.rows)

    def test_out_of_order_chunk_index_reflected_correctly(self):
        """Simulates chunk 1 failing all retries and being skipped — chunk 3
        must still be labeled 200/3, not 200/2."""
        result = self.pp.report(SAMPLE_RESPONSE, chunk_index=3)
        assert all(row.declaration_ref == "200/3" for row in result.rows)

    def test_missing_chunk_index_yields_no_suffix(self):
        result = self.pp.report(SAMPLE_RESPONSE, chunk_index=None)
        assert all(row.declaration_ref == "200" for row in result.rows)
