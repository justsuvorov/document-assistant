from pathlib import Path

from document_assistant.cargo.special_conditions_matcher import PolicyIdentityExtractor, SpecialConditionsMatcher

SAMPLE_PATH = Path(__file__).parents[2] / "tests" / "spec_conditions.xlsx"


class TestSpecialConditionsMatcher:
    """Uses the real sample workbook (thousands of rows, two relevant sheets:
    "ГП" and "ОБОРОННЫЙ") to verify only the matching rows are pulled out —
    not the whole file, which used to blow the LLM's context window."""

    def setup_method(self):
        self.matcher = SpecialConditionsMatcher()

    def test_matches_gp_sheet_by_policy_number(self):
        result = self.matcher.match(str(SAMPLE_PATH), "2518013GR1941", None)
        assert "Ответственному акцепт + КСД в Excel" in result
        assert "2518013GR1941" in result

    def test_gp_match_is_small_not_a_dump_of_the_whole_sheet(self):
        result = self.matcher.match(str(SAMPLE_PATH), "2518013GR1941", None)
        assert len(result) < 500
        # Other policies' rows must not leak in
        assert "Санрайз Логистик" not in result

    def test_matches_defense_sheet_by_contract_number(self):
        result = self.matcher.match(str(SAMPLE_PATH), "2600A13GR1339AZOAT", None)
        assert "ДНПП" in result
        assert "Все Декларации" in result

    def test_matches_defense_sheet_by_insurant_name(self):
        result = self.matcher.match(str(SAMPLE_PATH), None, "ПАО «ДНПП»")
        assert "ДНПП" in result

    def test_no_match_returns_empty(self):
        result = self.matcher.match(str(SAMPLE_PATH), "NONEXISTENT-NUMBER", "Nobody LLC")
        assert result == ""

    def test_no_identity_given_returns_empty(self):
        result = self.matcher.match(str(SAMPLE_PATH), None, None)
        assert result == ""


class TestPolicyIdentityExtractor:
    def setup_method(self):
        self.extractor = PolicyIdentityExtractor()

    def test_extracts_policy_number(self):
        text = "Декларация № 201 на условиях Генерального полиса № 250D013GR1837"
        assert self.extractor.extract_number(text) == "250D013GR1837"

    def test_extracts_insurant(self):
        text = "Страхователь: ООО «ИТЭ ЭКСПРЕСС ЛОГИСТИКА»\n\nСтраховщик: САО «ВСК»"
        assert self.extractor.extract_insurant(text) == "ООО «ИТЭ ЭКСПРЕСС ЛОГИСТИКА»"

    def test_no_number_in_text_returns_none(self):
        assert self.extractor.extract_number("Просто какой-то текст без номеров") is None

    def test_no_insurant_in_text_returns_none(self):
        assert self.extractor.extract_insurant("Просто какой-то текст без страхователя") is None
