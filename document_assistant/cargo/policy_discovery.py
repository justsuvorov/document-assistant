from pathlib import Path

from document_assistant.cargo.filename_parsing import PolicyFilenameParser
from document_assistant.cargo.models import PolicySource
from document_assistant.core.parsers import DataParser


class PolicyFolderScanner:
    """Lists the general policy and ДС files in a policy folder.

    Only the top level of ``policy_folder`` is scanned (excludes any nested
    "Декларации" subfolder). Results are sorted policy-first, then ДС in
    ascending precedence order (earliest valid_from/ds_number first, latest
    last) — this order is what "latest ДС wins" merging relies on.
    """

    def __init__(self, parser: PolicyFilenameParser | None = None):
        self._parser = parser or PolicyFilenameParser()

    def scan(self, policy_folder: str) -> list[PolicySource]:
        folder = Path(policy_folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Папка полиса не найдена: {policy_folder}")

        sources: list[PolicySource] = []
        for file in sorted(folder.iterdir()):
            if not file.is_file() or file.suffix.lower() not in DataParser._SUPPORTED:
                continue
            source = self._parser.parse(str(file))
            if source is not None:
                sources.append(source)

        sources.sort(key=lambda s: s.sort_key())
        return sources
