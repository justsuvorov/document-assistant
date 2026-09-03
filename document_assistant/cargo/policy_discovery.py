from pathlib import Path

from document_assistant.cargo.filename_parsing import PolicyFilenameParser
from document_assistant.cargo.document_files import is_generated_artifact, is_supported_document
from document_assistant.cargo.models import PolicySource


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
            if is_supported_document(entry):
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
            if is_supported_document(file):
                return PolicySource(kind="policy", file_path=str(file), raw_filename=file.stem)
        return None

    def _find_ds(self, policy_folder: str, override: str | None) -> list[PolicySource]:
        folder = self.resolve_ds_folder(policy_folder, override, verbose=True)
        if folder is None:
            return []

        print(f"[INFO] Папка ДС: {folder}", flush=True)

        ds_subfolders = [
            d for d in sorted(folder.iterdir())
            if d.is_dir() and self._parser.parse_ds_folder(d) is not None
        ]
        if ds_subfolders:
            return self._from_ds_subfolders(ds_subfolders)
        return self._from_flat_files(folder)

    def _from_ds_subfolders(self, subfolders: list[Path]) -> list[PolicySource]:
        """Each ДС in its own folder («ДС 1 (п.5, п.11.9)/ДС - 1.docx»).

        The folder name — not the file name — carries the amended clause
        numbers, and the folder also holds attachments (листы согласования,
        перечни, служебные выгрузки). Taking every file here is what turned
        14 ДС into 27 sources and sent a лист согласования to the LLM as if
        it were the agreement.
        """
        sources = []
        for d in subfolders:
            source = self._parser.parse_ds_folder(d)
            body = self._pick_ds_body(d)
            if body is None:
                print(f"[WARN] ДС {source.ds_number}: в папке «{d.name}» нет документа ДС", flush=True)
                continue
            source.file_path = str(body)
            source.raw_filename = body.stem
            sources.append(source)
            print(
                f"[INFO] ДС {source.ds_number}: {body.name}"
                + (f" (пункты: {', '.join(source.clause_numbers)})" if source.clause_numbers
                   else " (пункты не указаны в имени папки)"),
                flush=True,
            )
        return sources

    def _pick_ds_body(self, ds_folder: Path) -> Path | None:
        """The agreement document itself, not its attachments. Prefers a Word
        file whose own name reads as a ДС."""
        candidates = [
            f for f in sorted(ds_folder.rglob("*"))
            if is_supported_document(f)
            and not self._parser.is_auxiliary_name(f.stem)
        ]
        if not candidates:
            return None

        def rank(f: Path) -> tuple:
            is_word = f.suffix.lower() in (".docx", ".doc")
            parses_as_ds = self._parser.parse_ds(str(f)) is not None
            return (not parses_as_ds, not is_word, len(f.name))

        return min(candidates, key=rank)

    def _from_flat_files(self, folder: Path) -> list[PolicySource]:
        """All ДС as loose files in one folder («ДС/ДС 1 (п.9).docx»)."""
        by_number: dict[int, PolicySource] = {}
        skipped = []
        for file in sorted(folder.rglob("*")):
            if not file.is_file():
                continue
            if not is_supported_document(file):
                if not is_generated_artifact(file) and not file.name.startswith("~"):
                    skipped.append(f"{file.name} (неподдерживаемый формат {file.suffix})")
                continue
            if self._parser.is_auxiliary_name(file.stem):
                skipped.append(f"{file.name} (приложение к ДС, не сам ДС)")
                continue
            source = self._parser.parse_ds(str(file))
            if source is None:
                skipped.append(f"{file.name} (не распознан номер ДС в имени файла)")
                continue
            existing = by_number.get(source.ds_number)
            if existing is None:
                by_number[source.ds_number] = source
            else:
                skipped.append(f"{file.name} (дубль ДС {source.ds_number}, взят {Path(existing.file_path).name})")

        if skipped:
            print(
                f"[WARN] В папке ДС пропущено файлов — {len(skipped)}: " + "; ".join(skipped[:10]),
                flush=True,
            )
        return list(by_number.values())


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
