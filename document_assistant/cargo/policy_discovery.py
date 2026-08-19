from pathlib import Path

from document_assistant.cargo.filename_parsing import PolicyFilenameParser
from document_assistant.cargo.models import PolicySource
from document_assistant.core.parsers import DataParser


class PolicyFolderScanner:
    """Locates the general policy file and the ДС files for a policy folder.

    Default layout:
        {policy_folder}/ГП ... .docx      — general policy (filename starts with "ГП")
        {policy_folder}/ДС/*.docx         — addenda ("ДС N (п.X, ...)")

    Both can be overridden explicitly (``policy_file_override`` — a direct
    path to the policy file; ``ds_folder_override`` — a direct path to the
    ДС folder), bypassing the default filename-based/location-based lookup.

    Result is sorted policy-first, then ДС ascending by number — the order
    ClauseMerger relies on for "latest ДС wins".
    """

    DS_SUBFOLDER_NAME = "ДС"

    def __init__(self, parser: PolicyFilenameParser | None = None):
        self._parser = parser or PolicyFilenameParser()

    def scan(
        self,
        policy_folder: str,
        policy_file_override: str | None = None,
        ds_folder_override: str | None = None,
    ) -> list[PolicySource]:
        policy_source = self._find_policy(policy_folder, policy_file_override)
        ds_sources = self._find_ds(policy_folder, ds_folder_override)

        sources: list[PolicySource] = ([policy_source] if policy_source else []) + ds_sources
        if not sources:
            raise ValueError(
                f"В папке полиса не найдено ни ген.полиса (файл 'ГП ...'), ни ДС "
                f"(папка '{self.DS_SUBFOLDER_NAME}'): {policy_folder}"
            )

        sources.sort(key=lambda s: s.sort_key())
        return sources

    def _find_policy(self, policy_folder: str, override: str | None) -> PolicySource | None:
        if override:
            path = Path(override)
            if not path.is_file():
                raise FileNotFoundError(f"Файл генерального полиса не найден: {override}")
            return PolicySource(kind="policy", file_path=str(path), raw_filename=path.stem)

        folder = Path(policy_folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Папка полиса не найдена: {policy_folder}")

        for file in sorted(folder.iterdir()):
            if not file.is_file() or file.suffix.lower() not in DataParser._SUPPORTED:
                continue
            source = self._parser.parse_policy(str(file))
            if source is not None:
                return source
        return None

    def _find_ds(self, policy_folder: str, override: str | None) -> list[PolicySource]:
        folder = Path(override) if override else Path(policy_folder) / self.DS_SUBFOLDER_NAME
        if override and not folder.is_dir():
            raise FileNotFoundError(f"Папка ДС не найдена: {override}")
        if not folder.is_dir():
            return []

        sources = []
        for file in sorted(folder.iterdir()):
            if not file.is_file() or file.suffix.lower() not in DataParser._SUPPORTED:
                continue
            source = self._parser.parse_ds(str(file))
            if source is not None:
                sources.append(source)
        return sources
