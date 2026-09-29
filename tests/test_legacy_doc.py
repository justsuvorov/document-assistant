"""Reading old binary .doc files.

Regression: a general policy saved as legacy .doc failed with "is not a Word
file, content type is ...". The source was then skipped and the rules matrix
was built from the ДС alone — declarations got reconciled against a matrix
with no base policy clauses, which looked like widespread validation
nonsense rather than a read error.
"""
from pathlib import Path

import pytest

from document_assistant.core.legacy_word import LegacyWordConversionError, LegacyWordConverter
from document_assistant.core.parsers import DataParser


def _word_available() -> bool:
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    try:
        pythoncom.CoInitialize()
        # DispatchEx: never attach to (and then quit) a Word the
        # developer has open with their own documents.
        app = win32com.client.DispatchEx("Word.Application")
        app.Quit()
        return True
    except Exception:
        return False
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


needs_word = pytest.mark.skipif(
    not _word_available(), reason="Microsoft Word недоступен на этой машине"
)


@pytest.fixture(scope="module")
def legacy_doc(tmp_path_factory) -> Path:
    """A genuine legacy .doc, written by Word itself."""
    if not _word_available():
        pytest.skip("Microsoft Word недоступен")
    import pythoncom
    import win32com.client

    target = tmp_path_factory.mktemp("legacy") / "ГП тестовый.doc"
    pythoncom.CoInitialize()
    app = win32com.client.DispatchEx("Word.Application")
    app.Visible = False
    try:
        doc = app.Documents.Add()
        doc.Content.Text = (
            "ГЕНЕРАЛЬНЫЙ ПОЛИС\n"
            "5.4. Объект страхования: оборудование.\n"
            "15. Франшиза: 10000 руб."
        )
        doc.SaveAs(str(target), FileFormat=0)   # wdFormatDocument — legacy .doc
        doc.Close(False)
    finally:
        app.Quit()
        pythoncom.CoUninitialize()
    return target


@needs_word
class TestLegacyDocReading:
    def test_plain_docx_parser_cannot_read_it(self, legacy_doc: Path):
        """Documents the underlying limitation the fallback exists for."""
        from docx import Document
        with pytest.raises(Exception):
            Document(str(legacy_doc))

    def test_dataparser_reads_legacy_doc(self, legacy_doc: Path):
        text = DataParser(str(legacy_doc)).origin_data(str(legacy_doc))
        assert "ГЕНЕРАЛЬНЫЙ ПОЛИС" in text
        assert "Объект страхования" in text

    def test_clause_numbers_survive_conversion(self, legacy_doc: Path):
        """Clause numbers are the merge key for the rules matrix."""
        text = DataParser(str(legacy_doc)).origin_data(str(legacy_doc))
        assert "5.4" in text
        assert "15." in text

    def test_converter_cleans_up_its_temp_file(self, legacy_doc: Path):
        converter = LegacyWordConverter()
        converted = converter.convert_to_docx(str(legacy_doc))
        assert Path(converted).exists()
        converter.cleanup(converted)
        assert not Path(converted).exists()


class TestFailureMessage:
    """On a machine without Word the operator must get a message naming the
    file and the fix, not a COM traceback."""

    def test_missing_pywin32_gives_actionable_message(self, tmp_path: Path, monkeypatch):
        broken = tmp_path / "ГП тестовый.doc"
        broken.write_bytes(b"\xd0\xcf\x11\xe0 not really a doc")

        import builtins
        real_import = builtins.__import__

        def no_win32(name, *args, **kwargs):
            if name in ("win32com", "win32com.client", "pythoncom"):
                raise ImportError("no pywin32 here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_win32)

        with pytest.raises(LegacyWordConversionError) as exc:
            DataParser(str(broken)).origin_data(str(broken))

        message = str(exc.value)
        assert "ГП тестовый.doc" in message
        assert ".docx" in message          # говорит, что делать

    @needs_word
    def test_word_recovers_unusual_content_instead_of_failing(self, tmp_path: Path):
        """Word is lenient: it opens odd files as text rather than refusing.
        Documented so nobody expects an exception here — the guard against
        garbage reaching the model is the matrix check, not the parser."""
        odd = tmp_path / "ГП странный.doc"
        odd.write_bytes("5.4. Объект страхования: оборудование".encode("cp1251"))

        text = DataParser(str(odd)).origin_data(str(odd))

        assert isinstance(text, str)
