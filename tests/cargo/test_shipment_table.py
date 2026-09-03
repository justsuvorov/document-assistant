"""Regression coverage for the shipment-table split.

The bug this guards against: a real 2-shipment declaration was split into 15
chunks — one per markdown table row — because the title, the
Страхователь/Страховщик metadata block, the two-level column header and the
signature lines were all treated as shipments. That cost ~7x the LLM calls
and filled the report with junk 200/3 … 200/15 groups.
"""
from pathlib import Path

from document_assistant.ai.encoders import TextEncoder
from document_assistant.cargo.declaration_classifier import DeclarationType, DeclarationTypeClassifier
from document_assistant.cargo.shipment_table import find_shipment_rows, split_by_shipment
from document_assistant.core.parsers import DataParser

TESTS_DIR = Path(__file__).parents[2] / "tests"

# Shaped like a real declaration: preamble, metadata, two-level header,
# two shipments, signature block.
REALISTIC_MULTI = """\
| Декларация № | 511 | перевозок начавшихся | 2026-06-26 |
| на условиях Генерального полиса № 2506Q13GR2182 от 16.07.2025 г. | | | |
| Страхователь | | | ООО «ИТЭ ЭКСПРЕСС ЛОГИСТИКА» |
| Страховщик | | | САО "ВСК" |
| № п/п | Период страхования | | Наименование груза |
| | начало | окончание | |
| 1 | 2026-06-26 | 2026-09-26 | автомобили |
| 2 | 2026-06-26 | 2026-09-26 | автомобили |
| | СТРАХОВЩИК | | |
| | ______ /______/ | | |
"""


class TestFindShipmentRows:
    def test_only_sequence_numbered_rows_count_as_shipments(self):
        _, shipments = find_shipment_rows(REALISTIC_MULTI)
        assert len(shipments) == 2

    def test_no_pp_header_means_no_shipment_table(self):
        text = "| Страхователь | ООО Ромашка |\n| Груз | Оборудование |\n"
        header, shipments = find_shipment_rows(text)
        assert header is None
        assert shipments == []

    def test_stray_pp_label_is_not_a_table_header(self):
        """«№ п/п договора» in a 2-column vertical field list is a label, not
        a column header — it must not turn the rest of the form into rows."""
        text = (
            "| Страхователь | ООО Ромашка |\n"
            "| № п/п договора | 12345 |\n"
            "| Груз | Оборудование |\n"
            "| Маршрут | Москва-Казань |\n"
        )
        header, shipments = find_shipment_rows(text)
        assert header is None
        assert shipments == []


class TestSplitByShipment:
    def test_two_shipments_produce_two_chunks(self):
        chunks = split_by_shipment(REALISTIC_MULTI)
        assert len(chunks) == 2

    def test_each_chunk_keeps_document_level_context(self):
        """A shipment row alone can't be reconciled — Страхователь and the
        policy number live in the preamble."""
        for chunk in split_by_shipment(REALISTIC_MULTI):
            assert "Страхователь" in chunk
            assert "2506Q13GR2182" in chunk
            assert "№ п/п" in chunk

    def test_chunks_differ_only_by_their_shipment_row(self):
        first, second = split_by_shipment(REALISTIC_MULTI)
        assert "| 1 | 2026-06-26" in first
        assert "| 1 | 2026-06-26" not in second
        assert "| 2 | 2026-06-26" in second

    def test_signature_block_is_not_a_shipment(self):
        joined = "".join(split_by_shipment(REALISTIC_MULTI))
        assert "СТРАХОВЩИК" not in joined.split("| 1 |")[-1].split("| 2 |")[-1]

    def test_single_shipment_returns_whole_document(self):
        text = "| Страхователь | ООО Ромашка |\n| Груз | Оборудование |\n"
        assert split_by_shipment(text) == [text]


class TestRealFiles:
    def _text(self, filename: str) -> str:
        path = str(TESTS_DIR / filename)
        return TextEncoder().prepared_data(DataParser(path).origin_data(path))

    def test_511_two_shipments_yield_two_chunks_not_fifteen(self):
        text = self._text("511 не совпадает.xlsx")
        assert DeclarationTypeClassifier().classify(text) is DeclarationType.MULTI
        assert len(split_by_shipment(text)) == 2

    def test_511_chunks_carry_the_insurant(self):
        for chunk in split_by_shipment(self._text("511 не совпадает.xlsx")):
            assert "ЭКСПРЕСС ЛОГИСТИКА" in chunk

    def test_vertical_forms_stay_one_chunk(self):
        for filename in ("508 совпадает.xls", "1417 не совпадает.xls"):
            text = self._text(filename)
            assert DeclarationTypeClassifier().classify(text) is DeclarationType.SINGLE
            assert len(split_by_shipment(text)) == 1
