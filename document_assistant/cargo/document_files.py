"""Which files on a client share are actually readable documents.

Network folders carry more than the documents themselves. The one that
breaks parsing is Microsoft Office's lock file: opening «ДС - 1.docx» in
Word creates «~$ДС - 1.docx» beside it — same extension, plausible name, but
not a valid OOXML package. Feeding it to python-docx raises
PackageNotFoundError, which used to abort a whole reconciliation run.

Every scan in this package goes through here so the exclusion cannot be
added in one place and forgotten in another.
"""
from pathlib import Path

from document_assistant.core.parsers import DataParser

# Office lock/owner files («~$name.docx»); also the classic temp prefix.
_TEMP_PREFIXES = ("~$", "~")
# Our own debug/cache output, written next to each processed source.
_GENERATED_SUFFIXES = ("_llm_debug.md", "_llm_output.json")


def is_office_temp(path: Path) -> bool:
    return path.name.startswith(_TEMP_PREFIXES)


def is_generated_artifact(path: Path) -> bool:
    return path.name.endswith(_GENERATED_SUFFIXES)


def is_supported_document(path: Path) -> bool:
    """A real, parseable document: right extension, not a lock file, not
    hidden, not something this pipeline generated itself."""
    return (
        path.is_file()
        and path.suffix.lower() in DataParser._SUPPORTED
        and not is_office_temp(path)
        and not path.name.startswith(".")
        and not is_generated_artifact(path)
    )
