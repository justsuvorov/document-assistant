from document_assistant.ai.encoders import TextEncoder


class TestTextEncoder:
    def setup_method(self):
        self.enc = TextEncoder()

    def test_returns_string(self):
        assert isinstance(self.enc.prepared_data("hello"), str)

    def test_empty_input(self):
        assert self.enc.prepared_data("") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert self.enc.prepared_data("  hello  ") == "hello"

    def test_collapses_excess_blank_lines(self):
        text = "line1\n\n\n\n\nline2"
        result = self.enc.prepared_data(text)
        assert "\n\n\n" not in result
        assert "line1" in result
        assert "line2" in result

    def test_removes_bom(self):
        text = "\ufeffДокумент"
        result = self.enc.prepared_data(text)
        assert result == "Документ"

    def test_strips_trailing_spaces_per_line(self):
        text = "строка 1   \nстрока 2  "
        result = self.enc.prepared_data(text)
        for line in result.splitlines():
            assert line == line.rstrip()

    def test_truncates_oversized_text(self):
        big = "а" * (TextEncoder._MAX_CHARS + 1000)
        result = self.enc.prepared_data(big)
        assert len(result) <= TextEncoder._MAX_CHARS + 100  # allow for suffix
        assert "обрезан" in result
