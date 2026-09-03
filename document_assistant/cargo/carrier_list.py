import re
from dataclasses import dataclass
from pathlib import Path

from document_assistant.ai.encoders import TextEncoder
from document_assistant.cargo.filename_parsing import PolicyFilenameParser
from document_assistant.core.parsers import DataParser

_CARRIER_KEYWORD = "перевозчик"


@dataclass
class CarrierList:
    """The «Перечень перевозчиков» attachment, when the policy has one."""
    file_path: str
    source_label: str      # "ДС 4 (перевозчики)" | "текст ГП"
    text: str

    @property
    def found(self) -> bool:
        return bool(self.text.strip())


class CarrierListLocator:
    """Finds the «Перечень перевозчиков» attachment for a policy folder.

    The list lives as its own file, either alongside the policy text (a
    folder whose name contains "ГП", e.g. «текст ГП») or in the ДС folder.

    Priority, per the business rule:
    1. The LATEST ДС (highest ДС number) whose file name mentions
       "перевозчик" — a newer ДС replaces the carrier list of an older one.
    2. Otherwise the copy filed with the policy text («текст ГП»).

    When no such attachment exists, the policy simply has no carrier
    restriction and reconciliation proceeds without that check.
    """

    _DS_NUMBER_RE = re.compile(r"ДС\s*(?P<num>\d+)", re.IGNORECASE)

    def __init__(self, parser: PolicyFilenameParser | None = None):
        self._parser = parser or PolicyFilenameParser()
        self._encoder = TextEncoder()

    def locate(
        self,
        policy_folder: str,
        ds_folder_override: str | None = None,
        policy_file_override: str | None = None,
    ) -> CarrierList | None:
        candidate = (
            self._find_in_ds(policy_folder, ds_folder_override)
            or self._find_near_policy_text(policy_folder, policy_file_override)
        )
        if candidate is None:
            print(
                "[INFO] Перечень перевозчиков: приложение НЕ НАЙДЕНО "
                "(ни в папке ДС, ни рядом с текстом ГП) — проверка перевозчика не выполняется",
                flush=True,
            )
            return None

        path, source_label = candidate
        try:
            raw = DataParser(path).origin_data(path)
            text = self._encoder.prepared_data(raw)
        except Exception as e:
            print(f"[WARN] Перечень перевозчиков: не удалось прочитать файл {path} — {e}", flush=True)
            return None

        print(
            f"[INFO] Перечень перевозчиков: НАЙДЕН — {Path(path).name} "
            f"(источник: {source_label}, {len(text)} символов)",
            flush=True,
        )
        return CarrierList(file_path=path, source_label=source_label, text=text)

    def _find_in_ds(self, policy_folder: str, override: str | None) -> tuple[str, str] | None:
        folder = Path(override) if override else Path(policy_folder) / "ДС"
        if not folder.is_dir():
            return None

        matches: list[tuple[int, Path]] = []
        for file in folder.iterdir():
            if not file.is_file() or file.suffix.lower() not in DataParser._SUPPORTED:
                continue
            if _CARRIER_KEYWORD not in file.stem.lower():
                continue
            num_match = self._DS_NUMBER_RE.search(file.stem)
            matches.append((int(num_match.group("num")) if num_match else 0, file))

        if not matches:
            return None

        # Latest ДС wins — same precedence rule the rules matrix uses.
        ds_number, path = max(matches, key=lambda m: m[0])
        if len(matches) > 1:
            others = ", ".join(sorted(p.name for _, p in matches if p != path))
            print(
                f"[INFO] Перечень перевозчиков: найдено несколько в папке ДС, "
                f"взят самый поздний — {path.name} (не использованы: {others})",
                flush=True,
            )
        return str(path), f"ДС {ds_number}" if ds_number else "папка ДС"

    def _find_near_policy_text(self, policy_folder: str, policy_file_override: str | None) -> tuple[str, str] | None:
        for folder in self._policy_text_folders(policy_folder, policy_file_override):
            for file in sorted(folder.iterdir()):
                if not file.is_file() or file.suffix.lower() not in DataParser._SUPPORTED:
                    continue
                if _CARRIER_KEYWORD in file.stem.lower():
                    return str(file), f"текст ГП ({folder.name})"
        return None

    @staticmethod
    def _policy_text_folders(policy_folder: str, policy_file_override: str | None) -> list[Path]:
        """Folders that may hold the policy text: an explicit override's own
        directory first, then any subfolder of policy_folder whose name
        mentions ГП («текст ГП», «ГП 2026», …), then policy_folder itself."""
        folders: list[Path] = []
        if policy_file_override:
            parent = Path(policy_file_override).parent
            if parent.is_dir():
                folders.append(parent)

        root = Path(policy_folder)
        if root.is_dir():
            folders.extend(
                sorted(
                    d for d in root.iterdir()
                    if d.is_dir() and "гп" in d.name.lower()
                )
            )
            folders.append(root)

        seen, unique = set(), []
        for f in folders:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return unique
