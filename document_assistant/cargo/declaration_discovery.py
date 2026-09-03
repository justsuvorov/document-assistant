from pathlib import Path

from document_assistant.cargo.document_files import is_supported_document


class DeclarationDiscovery:
    """Resolves the ``declaration_paths`` request field into a concrete list
    of declaration file paths.

    - Each entry may be a file (used as-is) or a folder (scanned recursively
      for supported document files — declarations live under monthly
      subfolders, e.g. "Декларации/2026-08/200.xlsx").
    - If no paths are given at all, defaults to scanning
      "{policy_folder}/Декларации/".
    """

    DEFAULT_FOLDER_NAME = "Декларации"

    @classmethod
    def resolve(cls, policy_folder: str, declaration_paths: list[str] | None) -> list[str]:
        if declaration_paths:
            result: list[str] = []
            for entry in declaration_paths:
                path = Path(entry)
                if path.is_dir():
                    result.extend(cls._scan_folder(path))
                else:
                    result.append(str(path))
            return result

        return cls._scan_folder(Path(policy_folder) / cls.DEFAULT_FOLDER_NAME)

    @staticmethod
    def _scan_folder(folder: Path) -> list[str]:
        if not folder.is_dir():
            return []
        return sorted(str(f) for f in folder.rglob("*") if is_supported_document(f))
