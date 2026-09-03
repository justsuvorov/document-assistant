"""Regression coverage for the file filter.

The bug: an Office lock file («~$ДС - 1.docx», created while the document is
open in Word) was picked as a ДС body. It has a valid extension and a
plausible name, but is not an OOXML package — python-docx raised
PackageNotFoundError and the whole reconciliation run died.
"""
from pathlib import Path

import pytest

from document_assistant.cargo.document_files import (
    is_generated_artifact,
    is_office_temp,
    is_supported_document,
)


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


class TestOfficeTempFiles:
    @pytest.mark.parametrize("name", ["~$ДС - 1.docx", "~$policy.xlsx", "~temp.doc"])
    def test_detected_as_temp(self, name):
        assert is_office_temp(Path(name)) is True

    @pytest.mark.parametrize("name", ["ДС - 1.docx", "ГП полис.docx"])
    def test_real_documents_are_not_temp(self, name):
        assert is_office_temp(Path(name)) is False

    def test_lock_file_is_not_a_supported_document(self, tmp_path: Path):
        assert is_supported_document(_touch(tmp_path / "~$ДС - 1.docx")) is False

    def test_real_document_is_supported(self, tmp_path: Path):
        assert is_supported_document(_touch(tmp_path / "ДС - 1.docx")) is True


class TestGeneratedArtifacts:
    @pytest.mark.parametrize("name", ["ДС - 1_llm_debug.md", "ДС - 1_llm_output.json"])
    def test_detected(self, name):
        assert is_generated_artifact(Path(name)) is True

    def test_our_own_output_is_not_reprocessed(self, tmp_path: Path):
        assert is_supported_document(_touch(tmp_path / "x_llm_output.json")) is False


class TestOtherExclusions:
    def test_unsupported_extension(self, tmp_path: Path):
        assert is_supported_document(_touch(tmp_path / "notes.txt")) is False

    def test_hidden_file(self, tmp_path: Path):
        assert is_supported_document(_touch(tmp_path / ".hidden.docx")) is False

    def test_directory_is_not_a_document(self, tmp_path: Path):
        d = tmp_path / "ДС 1.docx"
        d.mkdir()
        assert is_supported_document(d) is False
