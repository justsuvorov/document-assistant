import pytest

from document_assistant.cargo.filename_parsing import DeclarationFilenameParser, PolicyFilenameParser


class TestPolicyFilenameParserPolicy:
    def setup_method(self):
        self.parser = PolicyFilenameParser()

    @pytest.mark.parametrize("filename", [
        "ГП страхования грузов.docx",
        "гп №123.pdf",
        "ГП.xlsx",
    ])
    def test_recognizes_policy(self, filename):
        result = self.parser.parse_policy(filename)
        assert result is not None
        assert result.kind == "policy"

    @pytest.mark.parametrize("filename", [
        "Договор ГП внутри текста.docx",   # "ГП" not at the start -> not recognized as policy
        "случайный файл.docx",
        "ДС 1 (п.9).docx",
    ])
    def test_non_policy_filename_returns_none(self, filename):
        assert self.parser.parse_policy(filename) is None

    def test_label(self):
        source = self.parser.parse_policy("ГП страхования грузов.docx")
        assert source.label == "Ген. полис"


class TestPolicyFilenameParserDs:
    def setup_method(self):
        self.parser = PolicyFilenameParser()

    def test_single_clause(self):
        result = self.parser.parse_ds("ДС 1 (п.9).docx")
        assert result is not None
        assert result.kind == "ds"
        assert result.ds_number == 1
        assert result.clause_numbers == ["9"]

    def test_multiple_clauses(self):
        result = self.parser.parse_ds("ДС 3 (п.9, п. 7).docx")
        assert result.ds_number == 3
        assert result.clause_numbers == ["9", "7"]

    def test_no_parenthetical_still_recognized_with_no_clauses(self):
        result = self.parser.parse_ds("ДС 2.docx")
        assert result.ds_number == 2
        assert result.clause_numbers == []

    def test_no_number_returns_none(self):
        assert self.parser.parse_ds("ГП страхования грузов.docx") is None
        assert self.parser.parse_ds("случайный файл.docx") is None

    def test_label(self):
        source = self.parser.parse_ds("ДС 3 (п.9, п. 7).docx")
        assert source.label == "ДС 3 (п.9, п.7)"


class TestDeclarationFilenameParser:
    def setup_method(self):
        self.parser = DeclarationFilenameParser()

    @pytest.mark.parametrize("filename,expected", [
        ("200.xlsx", "200"),
        ("Декларация 200.docx", "200"),
        ("decl_200_final.xlsx", "200"),
        ("200_1.xlsx", "200"),
    ])
    def test_parses_number(self, filename, expected):
        assert self.parser.parse_number(filename) == expected

    def test_no_number_returns_none(self):
        assert self.parser.parse_number("декларация.docx") is None
