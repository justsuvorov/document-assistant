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

        if policy_source:
            print(f"[INFO] Ген. полис: {Path(policy_source.file_path).name}", flush=True)
        else:
            print(f"[WARN] Ген. полис не найден в папке: {policy_folder}", flush=True)
        if ds_sources:
            ds_list = ", ".join(s.label for s in sorted(ds_sources, key=lambda s: s.sort_key()))
            print(f"[INFO] Найдено ДС ({len(ds_sources)}): {ds_list}", flush=True)
        else:
            print("[INFO] ДС не найдены", flush=True)

        return sources

    def find_policy_file(self, policy_folder: str, override: str | None = None) -> PolicySource | None:
        """Public entry point for callers that only need the ГП file (not the
        full ДС scan) — e.g. special-conditions lookup, which needs the policy
        document's own text to identify which policy is being reconciled."""
        return self._find_policy(policy_folder, override)

    def _find_policy(self, policy_folder: str, override: str | None) -> PolicySource | None:
        if override:
            path = Path(override)
            if not path.is_file():
                raise FileNotFoundError(f"Файл генерального полиса не найден: {override}")
            return PolicySource(kind="policy", file_path=str(path), raw_filename=path.stem)

        folder = Path(policy_folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Папка полиса не найдена: {policy_folder}")

        # The policy may be filed either as a document named "ГП ..." directly
        # in the policy folder, or inside a folder named for it («текст ГП»).
        for entry in sorted(folder.iterdir()):
            if entry.is_file() and entry.suffix.lower() in DataParser._SUPPORTED:
                source = self._parser.parse_policy(str(entry))
                if source is not None:
                    return source
            elif entry.is_dir() and self._parser.is_policy_folder_name(entry.name):
                source = self._first_document_in(entry)
                if source is not None:
                    return source
        return None

    @staticmethod
    def _first_document_in(folder: Path) -> PolicySource | None:
        for file in sorted(folder.iterdir()):
            if file.is_file() and file.suffix.lower() in DataParser._SUPPORTED:
                return PolicySource(kind="policy", file_path=str(file), raw_filename=file.stem)
        return None

    def _find_ds(self, policy_folder: str, override: str | None) -> list[PolicySource]:
        folder = self.resolve_ds_folder(policy_folder, override, verbose=True)
        if folder is None:
            return []

        print(f"[INFO] Папка ДС: {folder}", flush=True)

        # Recursive: some clients file each ДС in its own subfolder.
        sources, skipped = [], []
        for file in sorted(folder.rglob("*")):
            if not file.is_file():
                continue
            if file.suffix.lower() not in DataParser._SUPPORTED:
                skipped.append(f"{file.name} (неподдерживаемый формат {file.suffix})")
                continue
            source = self._parser.parse_ds(str(file))
            if source is None:
                skipped.append(f"{file.name} (не распознан номер ДС в имени файла)")
                continue
            sources.append(source)

        if skipped:
            print(
                f"[WARN] В папке ДС пропущено файлов — {len(skipped)}: " + "; ".join(skipped[:10]),
                flush=True,
            )
        return sources

    def resolve_ds_folder(
        self, policy_folder: str, override: str | None = None, verbose: bool = False
    ) -> Path | None:
        """Locate the addenda folder. Public so the carrier-list lookup uses
        the same tolerant resolution — otherwise a folder named «Доп.
        соглашения» would be found for the rules matrix but missed for
        carriers. ``verbose`` is off by default so only the scan pass logs."""
        if override:
            folder = Path(override)
            if not folder.is_dir():
                raise FileNotFoundError(f"Папка ДС не найдена: {override}")
            return folder

        root = Path(policy_folder)
        if not root.is_dir():
            return None

        exact = root / self.DS_SUBFOLDER_NAME
        if exact.is_dir():
            return exact

        # Fall back to a tolerant match — the folder is named by hand, so it
        # may read «Доп. соглашения», or carry a Latin "C" homoglyph that
        # makes the exact join above miss a folder that looks correct.
        subfolders = [d for d in sorted(root.iterdir()) if d.is_dir()]
        for d in subfolders:
            if self._parser.is_ds_folder_name(d.name):
                if verbose:
                    print(
                        f"[INFO] Папка ДС найдена по нестандартному имени: «{d.name}» "
                        f"(ожидалось «{self.DS_SUBFOLDER_NAME}»)",
                        flush=True,
                    )
                return d

        if verbose:
            if subfolders:
                print(
                    f"[WARN] Папка ДС не найдена в {policy_folder}. "
                    f"Просмотрены подпапки: {', '.join(d.name for d in subfolders)}",
                    flush=True,
                )
            else:
                print(f"[WARN] Папка ДС не найдена: в {policy_folder} нет подпапок вообще", flush=True)
        return None
