from document_assistant.cargo.declaration_numbering import DeclarationNumbering


class TestDeclarationNumbering:
    def test_row_label_single(self):
        assert DeclarationNumbering.row_label("200", None) == "200"

    def test_row_label_multi(self):
        assert DeclarationNumbering.row_label("200", 1) == "200/1"
        assert DeclarationNumbering.row_label("200", 3) == "200/3"

    def test_output_filename_default_ext(self):
        assert DeclarationNumbering.output_filename("200") == "200 – результат проверки.xlsx"

    def test_output_filename_custom_ext(self):
        assert DeclarationNumbering.output_filename("200", ".docx") == "200 – результат проверки.docx"
