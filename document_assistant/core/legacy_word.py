"""Reading old binary Word documents (.doc).

python-docx only understands OOXML (.docx). A legacy .doc is an OLE2 binary
and fails with "is not a Word file, content type is ...". That failure was
silent in effect: the general policy was skipped and the rules matrix got
built from the ДС alone, so declarations were reconciled against a matrix
with no base policy clauses at all.

Conversion goes through the Word installation on the machine (COM), which
insurance workstations have. The converted .docx is then read by the normal
Word parser, so tables and headings come out identically to a native .docx.
"""
import os
import tempfile
from pathlib import Path

# wdFormatXMLDocument — .docx
_WD_FORMAT_DOCX = 16


class LegacyWordConversionError(RuntimeError):
    """Raised with an operator-actionable message when .doc cannot be read."""


class LegacyWordConverter:
    """Converts a legacy .doc to .docx using the local Word installation."""

    def convert_to_docx(self, file_path: str) -> str:
        """Returns the path of a temporary .docx. Caller deletes it."""
        try:
            import pythoncom
            import win32com.client
        except ImportError as e:
            raise LegacyWordConversionError(
                f"Файл '{Path(file_path).name}' сохранён в старом формате .doc, "
                "для чтения нужен компонент pywin32, которого нет в сборке. "
                "Пересохраните файл как .docx."
            ) from e

        source = str(Path(file_path).resolve())
        target = os.path.join(tempfile.mkdtemp(prefix="legacy_doc_"), "converted.docx")

        # The endpoint runs inside a FastAPI worker thread; COM must be
        # initialized per thread or Dispatch fails with CoInitialize errors.
        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            # DispatchEx, not Dispatch: Dispatch attaches to a Word the
            # operator may already have open, and our Quit() would then close
            # their documents. DispatchEx always starts a separate process
            # that only we own.
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0          # no "convert file?" dialogs on a server
            doc = word.Documents.Open(
                source,
                ReadOnly=True,
                AddToRecentFiles=False,
                ConfirmConversions=False,
                Visible=False,
            )
            doc.SaveAs2(target, FileFormat=_WD_FORMAT_DOCX)
            return target
        except Exception as e:
            raise LegacyWordConversionError(
                f"Не удалось прочитать файл '{Path(file_path).name}' в старом формате .doc: {e}. "
                "Проверьте, что на машине установлен Microsoft Word, либо пересохраните файл как .docx."
            ) from e
        finally:
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            try:
                if word is not None:
                    word.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    @staticmethod
    def cleanup(converted_path: str) -> None:
        try:
            os.remove(converted_path)
            os.rmdir(os.path.dirname(converted_path))
        except OSError:
            pass
