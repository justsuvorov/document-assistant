import pytest

from document_assistant.cargo import result_consistency
from document_assistant.cargo.models import ReconciliationRow


def _row(result: str, comment: str = "") -> ReconciliationRow:
    return ReconciliationRow("200", "Тариф", "п.5", result, comment)


class TestNormalizeStatus:
    @pytest.mark.parametrize("raw", ["совпадает", "Совпадает", " СОВПАДАЕТ ", "совпадает."])
    def test_match_variants(self, raw):
        assert result_consistency.normalize_status(raw) == "совпадает"

    @pytest.mark.parametrize("raw", [
        "не совпадает", "Не совпадает", "не знаю", "не определено", "", "частично", "???",
    ])
    def test_everything_else_is_mismatch(self, raw):
        """Anything not clearly a positive match is treated as a mismatch — a
        false «не совпадает» costs a glance, a false «совпадает» hides a
        real discrepancy."""
        assert result_consistency.normalize_status(raw) == "не совпадает"


class TestContradictionDetection:
    @pytest.mark.parametrize("comment", [
        "В декларации 0,15%, а в полисе 0,2% — значения отличаются",
        "Обнаружено расхождение по сумме",
        "Данные не соответствуют полису",
        "Указано 100 вместо 200",
        "Поле в декларации отсутствует",
    ])
    def test_flags_match_contradicted_by_comment(self, comment):
        rows = [_row("совпадает", comment)]
        result_consistency.apply(rows, "200")
        assert rows[0].needs_review is True

    @pytest.mark.parametrize("comment", [
        "Полное совпадение",
        "Значения идентичны",
        "",
        "совпадает",
    ])
    def test_clean_match_not_flagged(self, comment):
        rows = [_row("совпадает", comment)]
        result_consistency.apply(rows, "200")
        assert rows[0].needs_review is False

    def test_status_echo_in_comment_does_not_self_trigger(self):
        """A comment that merely restates «не совпадает» on a mismatch row is
        not a contradiction — and a mismatch row is never flagged anyway."""
        rows = [_row("не совпадает", "не совпадает: разные значения")]
        result_consistency.apply(rows, "200")
        assert rows[0].needs_review is False

    def test_mismatch_row_is_never_flagged(self):
        rows = [_row("не совпадает", "значения отличаются")]
        result_consistency.apply(rows, "200")
        assert rows[0].needs_review is False

    def test_verdict_is_not_silently_rewritten(self):
        """The contradictory verdict stays as the model reported it — a human
        decides. Only the review flag is added."""
        rows = [_row("совпадает", "значения отличаются")]
        result_consistency.apply(rows, "200")
        assert rows[0].result == "совпадает"
        assert rows[0].needs_review is True
