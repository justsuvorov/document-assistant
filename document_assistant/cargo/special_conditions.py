from pathlib import Path

from document_assistant.ai.promt_builders import NormativeBaseLoader
from document_assistant.cargo.policy_discovery import PolicyFolderScanner
from document_assistant.cargo.special_conditions_matcher import PolicyIdentityExtractor, SpecialConditionsMatcher
from document_assistant.core.parsers import DataParser
from document_assistant.core.settings import settings

_EXCEL_EXTS = {".xlsx", ".xlsm", ".xls"}


class SpecialConditionsLoader:
    """Loads "особые условия" (deviations from the standard reconciliation
    process): a global file shared by all clients, and/or a per-client file
    living in the policy folder.

    Both are loaded when present and concatenated — the per-client text is
    labeled as taking precedence on conflict (in the prompt text itself, not
    programmatically, since resolving an actual conflict requires judgement
    the LLM should make case by case).

    The global file is a shared reference workbook (thousands of rows, many
    sheets) — it is never dumped whole into the prompt. Instead, the current
    policy's number/insurant is extracted from the ГП document text, and only
    the matching rows of the "ГП"/"ОБОРОННЫЙ" sheets are pulled in via
    SpecialConditionsMatcher. Non-Excel global files (a small dedicated
    note) are still loaded in full, since there's nothing to look up.
    """

    _CLIENT_KEYWORDS = ("особые условия", "особых условий")

    def __init__(
        self,
        loader: NormativeBaseLoader | None = None,
        matcher: SpecialConditionsMatcher | None = None,
        extractor: PolicyIdentityExtractor | None = None,
    ):
        self._loader = loader or NormativeBaseLoader()
        self._matcher = matcher or SpecialConditionsMatcher()
        self._extractor = extractor or PolicyIdentityExtractor()

    def load(self, policy_folder: str, explicit_path: str | None = None) -> str:
        global_text = self._load_global(policy_folder)

        client_path = explicit_path or self._discover(policy_folder)
        client_text = self._loader.load(client_path) if client_path else ""

        if client_path and client_text:
            print(f"[INFO] Особые условия клиента: загружены — {client_path}", flush=True)
        elif client_path and not client_text:
            print(f"[WARN] Особые условия клиента: файл не найден — {client_path}", flush=True)
        else:
            print("[INFO] Особые условия клиента: файл не задан и не найден автопоиском", flush=True)

        parts = []
        if global_text:
            parts.append(f"### Общие особые условия\n\n{global_text}")
        if client_text:
            parts.append(f"### Особые условия клиента (приоритет выше при конфликте)\n\n{client_text}")
        return "\n\n---\n\n".join(parts)

    def _load_global(self, policy_folder: str) -> str:
        global_path = settings.special_conditions_global_path
        if not global_path:
            print("[INFO] Особые условия (общие): путь не задан в .env", flush=True)
            return ""
        if not Path(global_path).exists():
            print(f"[WARN] Особые условия (общие): путь задан, но файл не найден — {global_path}", flush=True)
            return ""

        if Path(global_path).suffix.lower() in _EXCEL_EXTS:
            return self._load_global_lookup(policy_folder, global_path)

        text = self._loader.load(global_path)
        if text:
            print(f"[INFO] Особые условия (общие): загружены целиком — {global_path}", flush=True)
        return text

    def _load_global_lookup(self, policy_folder: str, global_path: str) -> str:
        """SPECIAL_CONDITIONS_GLOBAL_PATH points at a shared reference workbook
        with thousands of rows — dumping it whole blows the LLM's context
        window (this used to cause 400 Bad Request). Instead, find the
        current policy's number/insurant from the ГП document and look up
        only the matching rows."""
        number, insurant = self._extract_policy_identity(policy_folder)
        if not number and not insurant:
            return ""

        text = self._matcher.match(global_path, number, insurant)
        if text:
            print(f"[INFO] Особые условия (общие): найдено совпадение в {global_path}", flush=True)
        else:
            print(
                f"[INFO] Особые условия (общие): совпадений для текущего полиса не найдено в {global_path}",
                flush=True,
            )
        return text

    def _extract_policy_identity(self, policy_folder: str) -> tuple[str | None, str | None]:
        try:
            policy_source = PolicyFolderScanner().find_policy_file(policy_folder)
        except FileNotFoundError:
            policy_source = None
        if policy_source is None:
            print("[WARN] Особые условия (общие): не найден файл ГП — номер полиса не определён", flush=True)
            return None, None

        try:
            policy_text = DataParser(policy_source.file_path).origin_data(policy_source.file_path)
        except Exception as e:
            print(f"[WARN] Особые условия (общие): не удалось прочитать файл ГП — {e}", flush=True)
            return None, None

        number = self._extractor.extract_number(policy_text)
        insurant = self._extractor.extract_insurant(policy_text)
        print(
            f"[INFO] Особые условия (общие): ключ поиска — № {number or '?'}, "
            f"страхователь «{insurant or '?'}»",
            flush=True,
        )
        return number, insurant

    def _discover(self, policy_folder: str) -> str | None:
        folder = Path(policy_folder)
        if not folder.is_dir():
            return None
        for file in sorted(folder.iterdir()):
            if not file.is_file():
                continue
            lowered = file.stem.lower()
            if any(kw in lowered for kw in self._CLIENT_KEYWORDS):
                return str(file)
        return None
