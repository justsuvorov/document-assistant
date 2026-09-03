from pathlib import Path

from docx import Document

from document_assistant.cargo.carrier_list import CarrierListLocator


def _doc(path: Path, text: str = "ООО Ромашка, ООО Вектор") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    d = Document()
    d.add_paragraph(text)
    d.save(path)
    return path


class TestNotFound:
    def test_no_attachment_returns_none(self, tmp_path: Path):
        _doc(tmp_path / "ГП страхования грузов.docx", "Условия полиса")
        assert CarrierListLocator().locate(str(tmp_path)) is None

    def test_missing_folder_returns_none(self, tmp_path: Path):
        assert CarrierListLocator().locate(str(tmp_path / "missing")) is None


class TestFoundInDsFolder:
    def test_single_ds_carrier_list(self, tmp_path: Path):
        _doc(tmp_path / "ДС" / "ДС 2 (перевозчики).docx", "ООО Ромашка")

        result = CarrierListLocator().locate(str(tmp_path))

        assert result is not None
        assert result.found
        assert "перевозчики" in Path(result.file_path).stem.lower()
        assert "Ромашка" in result.text

    def test_latest_ds_wins(self, tmp_path: Path):
        """Business rule: take the carrier list from the LAST ДС that has one."""
        _doc(tmp_path / "ДС" / "ДС 2 (перевозчики).docx", "СТАРЫЙ перевозчик")
        _doc(tmp_path / "ДС" / "ДС 7 (перевозчики).docx", "НОВЫЙ перевозчик")
        _doc(tmp_path / "ДС" / "ДС 4 (перевозчики).docx", "СРЕДНИЙ перевозчик")

        result = CarrierListLocator().locate(str(tmp_path))

        assert "НОВЫЙ" in result.text
        assert result.source_label == "ДС 7"

    def test_ds_folder_override_is_used(self, tmp_path: Path):
        custom = tmp_path / "custom_ds"
        _doc(custom / "ДС 3 (перевозчики).docx", "ООО Из переопределённой папки")

        result = CarrierListLocator().locate(str(tmp_path), ds_folder_override=str(custom))

        assert "переопределённой" in result.text


class TestFoundNearPolicyText:
    def test_carrier_list_in_policy_text_folder(self, tmp_path: Path):
        _doc(tmp_path / "текст ГП" / "ГП основной.docx", "Условия")
        _doc(tmp_path / "текст ГП" / "Перечень перевозчиков.docx", "ООО Ромашка")

        result = CarrierListLocator().locate(str(tmp_path))

        assert result is not None
        assert "текст ГП" in result.source_label
        assert "Ромашка" in result.text

    def test_ds_takes_priority_over_policy_text(self, tmp_path: Path):
        _doc(tmp_path / "текст ГП" / "Перечень перевозчиков.docx", "ИЗ ПАПКИ ГП")
        _doc(tmp_path / "ДС" / "ДС 1 (перевозчики).docx", "ИЗ ДС")

        result = CarrierListLocator().locate(str(tmp_path))

        assert "ИЗ ДС" in result.text

    def test_carrier_list_directly_in_policy_folder(self, tmp_path: Path):
        _doc(tmp_path / "ГП страхования.docx", "Условия")
        _doc(tmp_path / "Перечень перевозчиков.docx", "ООО Вектор")

        result = CarrierListLocator().locate(str(tmp_path))

        assert result is not None
        assert "Вектор" in result.text
