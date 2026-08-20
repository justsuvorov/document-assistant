from datetime import date
from pathlib import Path

from document_assistant.cargo.output_paths import PeriodMonthResolver, ReconciliationOutputResolver


class TestReconciliationOutputResolver:
    def test_resolves_sibling_path(self):
        result = ReconciliationOutputResolver.resolve("/net/share/2026-08/200.xlsx", "200")
        assert result == Path("/net/share/2026-08") / "200 – результат проверки.xlsx"

    def test_multi_row_output_filename_has_no_suffix(self):
        """Even for a multi-row declaration, the OUTPUT FILE is not suffixed —
        only the rows inside it carry 200/1, 200/2, ..."""
        result = ReconciliationOutputResolver.resolve("/net/share/2026-08/200.xlsx", "200")
        assert result.name == "200 – результат проверки.xlsx"


class TestPeriodMonthResolver:
    def test_expected_month_folder_default_format(self):
        assert PeriodMonthResolver.expected_month_folder(date(2026, 8, 15)) == "2026-08"

    def test_no_warning_when_period_start_unknown(self):
        assert PeriodMonthResolver.warn_if_mismatched("/net/share/2026-08/200.xlsx", None) is None

    def test_no_warning_when_folder_matches(self):
        warning = PeriodMonthResolver.warn_if_mismatched("/net/share/2026-08/200.xlsx", date(2026, 8, 15))
        assert warning is None

    def test_warns_when_folder_mismatches(self):
        warning = PeriodMonthResolver.warn_if_mismatched("/net/share/2026-07/200.xlsx", date(2026, 8, 15))
        assert warning is not None
        assert "2026-07" in warning
        assert "2026-08" in warning
