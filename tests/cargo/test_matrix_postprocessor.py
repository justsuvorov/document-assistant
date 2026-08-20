from document_assistant.cargo.matrix_postprocessor import MatrixPostProcessor

SAMPLE_RESPONSE = """\
Вот извлечённые пункты документа.

| Пункт (номер/название) | Актуальный текст/значение | Комментарий |
|---|---|---|
| 3.2 Объект страхования | Оборудование и запчасти | Уточнено в п.3.2 |
| 5.1 Франшиза | 10000 руб. | |
"""


class TestMatrixPostProcessor:
    def setup_method(self):
        self.pp = MatrixPostProcessor()

    def test_parses_all_rows(self):
        result = self.pp.parse(SAMPLE_RESPONSE)
        assert len(result) == 2

    def test_fields(self):
        result = self.pp.parse(SAMPLE_RESPONSE)
        first = result[0]
        assert first.clause_id == "3.2 Объект страхования"
        assert first.effective_text == "Оборудование и запчасти"
        assert first.comment == "Уточнено в п.3.2"

    def test_empty_comment(self):
        result = self.pp.parse(SAMPLE_RESPONSE)
        assert result[1].comment == ""

    def test_empty_input(self):
        assert self.pp.parse("") == []

    def test_no_table(self):
        assert self.pp.parse("Пункты не найдены.") == []
