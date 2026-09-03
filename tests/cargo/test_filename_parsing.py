from pathlib import Path

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


class TestDsNameVariants:
    """Real folders are filled in by hand — «ДС №1», «ДС_1», «Доп. соглашение 1»
    and a Latin-"C" «ДC» all appear in practice and must all parse."""

    def setup_method(self):
        self.parser = PolicyFilenameParser()

    @pytest.mark.parametrize("filename,expected_num", [
        ("ДС 1 (п.9).docx", 1),
        ("ДС №1 (п.9).docx", 1),
        ("ДС N1.docx", 1),
        ("ДС_1.docx", 1),
        ("ДС-1.docx", 1),
        ("ДС1.docx", 1),
        ("Доп. соглашение 1.docx", 1),
        ("Дополнительное соглашение 7.docx", 7),
        ("ДС 1 от 01.01.2025.docx", 1),
    ])
    def test_number_variants(self, filename, expected_num):
        result = self.parser.parse_ds(filename)
        assert result is not None, f"{filename} должен распознаваться"
        assert result.ds_number == expected_num

    def test_latin_c_homoglyph_is_recognized(self):
        """«ДC» typed with a Latin C (U+0043) renders identically to «ДС»."""
        result = self.parser.parse_ds("\u0414\u0043 \u21163 (\u043f.7).docx")
        assert result is not None
        assert result.ds_number == 3
        assert result.clause_numbers == ["7"]

    def test_clause_numbers_with_number_sign(self):
        result = self.parser.parse_ds("ДС №2 (п.5, п. 7).docx")
        assert result.clause_numbers == ["5", "7"]


class TestDsFolderNames:
    def setup_method(self):
        self.parser = PolicyFilenameParser()

    @pytest.mark.parametrize("name", [
        "ДС", "дс", "\u0414\u0043", "Доп соглашения", "Доп. соглашения", "ДС (доп. соглашения)",
    ])
    def test_recognized_as_ds_folder(self, name):
        assert self.parser.is_ds_folder_name(name) is True

    @pytest.mark.parametrize("name", ["Декларации", "текст ГП", "Прочее"])
    def test_not_ds_folder(self, name):
        assert self.parser.is_ds_folder_name(name) is False

    def test_ds_folder_is_never_mistaken_for_policy_folder(self):
        for name in ("ДС", "Доп. соглашения", "ДС (доп. соглашения)"):
            assert self.parser.is_policy_folder_name(name) is False


class TestAuxiliaryAttachments:
    """Attachments carry the ДС number in their name («ЛС к ДС 1») and would
    otherwise be picked up as duplicate ДС and sent to the LLM."""

    def setup_method(self):
        self.parser = PolicyFilenameParser()

    @pytest.mark.parametrize("name", [
        "ЛС к ДС 1", "Лист согласования к ДС 2", "Согласование БКС", "Перечень перевозчиков",
    ])
    def test_recognized_as_auxiliary(self, name):
        assert self.parser.is_auxiliary_name(name) is True

    @pytest.mark.parametrize("name", ["ДС - 1", "ДС 2 (п.7)", "ГП (рефрижераторный риск)"])
    def test_agreement_documents_are_not_auxiliary(self, name):
        assert self.parser.is_auxiliary_name(name) is False


class TestDsFolderNameParsing:
    def setup_method(self):
        self.parser = PolicyFilenameParser()

    def test_clause_numbers_survive_dotted_folder_name(self):
        """Path.stem would read «.19)» as an extension and drop the closing
        paren, leaving the clause list unparseable."""
        source = self.parser.parse_ds_folder(Path("ДС 1 (п.5, п.11.9, п.18.2.19)"))
        assert source is not None
        assert source.ds_number == 1
        assert source.clause_numbers == ["5", "11.9", "18.2.19"]

    def test_simple_folder_name(self):
        source = self.parser.parse_ds_folder(Path("ДС 2 (п.7)"))
        assert source.ds_number == 2
        assert source.clause_numbers == ["7"]

    def test_non_ds_folder_returns_none(self):
        assert self.parser.parse_ds_folder(Path("Декларации")) is None
