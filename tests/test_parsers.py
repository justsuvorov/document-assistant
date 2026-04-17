import pytest
from pathlib import Path

from document_assistant.core.parsers import DataParser, Excel, Word, MarkdownTableBuilder


# ── MarkdownTableBuilder ──────────────────────────────────────────────────────

class TestMarkdownTableBuilder:
    def test_basic_table(self):
        rows = [["Заголовок 1", "Заголовок 2"], ["Ячейка A", "Ячейка B"]]
        md = MarkdownTableBuilder.from_rows(rows)
        lines = md.splitlines()
        assert lines[0].startswith("|")
        assert "---" in lines[1]
        assert "Ячейка A" in lines[2]

    def test_empty_input(self):
        assert MarkdownTableBuilder.from_rows([]) == ""

    def test_normalise_pads_short_rows(self):
        rows = [["A", "B", "C"], ["X"]]
        normalised = MarkdownTableBuilder.normalise(rows)
        assert len(normalised[1]) == 3
        assert normalised[1][1] == ""

    def test_normalise_stringifies_cells(self):
        rows = [[1, None, 3.14]]
        result = MarkdownTableBuilder.normalise(rows)
        assert result[0] == ["1", "", "3.14"]


# ── Excel parser ──────────────────────────────────────────────────────────────

class TestExcel:
    def test_reads_non_empty_sheet(self, excel_file):
        result = Excel().read_document(str(excel_file))
        assert "Данные" in result
        assert "ДТП" in result
        assert "Пожар" in result

    def test_skips_empty_sheet(self, excel_file):
        result = Excel().read_document(str(excel_file))
        assert "Пустой лист" not in result

    def test_all_empty_returns_empty_string(self, excel_file_all_empty):
        result = Excel().read_document(str(excel_file_all_empty))
        assert result == ""

    def test_output_is_markdown_table(self, excel_file):
        result = Excel().read_document(str(excel_file))
        assert "|" in result
        assert "---" in result


# ── Word parser ───────────────────────────────────────────────────────────────

class TestWord:
    def test_reads_heading(self, word_file):
        result = Word().read_document(str(word_file))
        assert "Требования к страхованию" in result

    def test_heading_has_markdown_prefix(self, word_file):
        result = Word().read_document(str(word_file))
        assert "# Требования к страхованию" in result

    def test_reads_paragraph(self, word_file):
        result = Word().read_document(str(word_file))
        assert "Клиент запрашивает страхование имущества." in result

    def test_reads_table(self, word_file):
        result = Word().read_document(str(word_file))
        assert "Пожар" in result
        assert "Затопление" in result
        assert "|" in result


# ── DataParser ────────────────────────────────────────────────────────────────

class TestDataParser:
    def test_routes_xlsx_to_excel(self, excel_file):
        parser = DataParser(str(excel_file))
        assert isinstance(parser.parser, Excel)

    def test_routes_docx_to_word(self, word_file):
        parser = DataParser(str(word_file))
        assert isinstance(parser.parser, Word)

    def test_unsupported_format_raises(self, tmp_path):
        bad_file = tmp_path / "file.csv"
        bad_file.write_text("a,b,c")
        with pytest.raises(ValueError, match="Unsupported file format"):
            DataParser(str(bad_file))

    def test_origin_data_collapses_blank_lines(self, excel_file):
        result = DataParser(str(excel_file)).origin_data(str(excel_file))
        assert "\n\n\n" not in result

    def test_origin_data_stripped(self, excel_file):
        result = DataParser(str(excel_file)).origin_data(str(excel_file))
        assert result == result.strip()
