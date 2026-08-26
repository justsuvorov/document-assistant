from pathlib import Path

from document_assistant.ai.encoders import TextEncoder
from document_assistant.cargo.declaration_classifier import DeclarationType, DeclarationTypeClassifier
from document_assistant.core.parsers import DataParser

TESTS_DIR = Path(__file__).parents[2] / "tests"


class TestDeclarationTypeClassifier:
    def setup_method(self):
        self.classifier = DeclarationTypeClassifier()

    def test_single_row_table_is_single(self):
        text = (
            "| № п/п | Груз | Маршрут |\n"
            "|---|---|---|\n"
            "| 1 | Оборудование | Москва-СПб |\n"
        )
        assert self.classifier.classify(text) == DeclarationType.SINGLE

    def test_multi_row_table_is_multi(self):
        text = (
            "| № п/п | Груз | Маршрут |\n"
            "|---|---|---|\n"
            "| 1 | Оборудование | Москва-СПб |\n"
            "| 2 | Металл | СПб-Казань |\n"
            "| 3 | Текстиль | Казань-Уфа |\n"
        )
        assert self.classifier.classify(text) == DeclarationType.MULTI

    def test_dense_rows_without_item_header_stay_single(self):
        # Regression: a numbered field list (no "№ п/п" table header) must
        # not be mistaken for a shipment table just because two unrelated
        # field-rows happen to have a similar filled-cell count.
        text = (
            "| Декларация | № 1417 | об отгрузке |\n"
            "|---|---|---|\n"
            "| 1. | Полное наименование груза | личные вещи |\n"
            "| 9. | Период страхования | 2026-07-24 | по | 2026-09-24 |\n"
            "| 10. | ТТН № | Invoice IL-1 | от | 2026-06-10 |\n"
        )
        assert self.classifier.classify(text) == DeclarationType.SINGLE

    def test_no_table_is_single(self):
        text = "Декларация на перевозку оборудования по маршруту Москва-СПб."
        assert self.classifier.classify(text) == DeclarationType.SINGLE

    def test_empty_text_is_single(self):
        assert self.classifier.classify("") == DeclarationType.SINGLE


class TestDeclarationTypeClassifierRealFiles:
    """Regression coverage using real declaration exports — synthetic examples
    alone missed the "numbered field list" shape that real single-shipment
    declarations can take (see test_dense_rows_without_item_header_stay_single)."""

    def setup_method(self):
        self.classifier = DeclarationTypeClassifier()

    def _classify_file(self, filename: str) -> DeclarationType:
        path = TESTS_DIR / filename
        raw = DataParser(str(path)).origin_data(str(path))
        encoded = TextEncoder().prepared_data(raw)
        return self.classifier.classify(encoded)

    def test_508_single_shipment_form_is_single(self):
        assert self._classify_file("508 совпадает.xls") == DeclarationType.SINGLE

    def test_511_two_shipment_table_is_multi(self):
        assert self._classify_file("511 не совпадает.xlsx") == DeclarationType.MULTI

    def test_1417_vertical_field_form_is_single(self):
        assert self._classify_file("1417 не совпадает.xls") == DeclarationType.SINGLE
