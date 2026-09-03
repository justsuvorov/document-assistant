"""Parse policy/ДС/declaration metadata out of file names, per the actual
customer convention:

    {policy_folder}/
    ├── ГП ... .docx              — general policy, filename starts with "ГП"
    ├── ДС/                       — subfolder holding all addenda
    │   ├── ДС 1 (п.9).docx       — ДС number 1, amends clause 9
    │   ├── ДС 2 (п.5).docx       — ДС number 2, amends clause 5
    │   └── ДС 3 (п.9, п. 7).docx — ДС number 3, amends clauses 9 and 7
    └── Декларации/...

ADJUST ME if real files deviate from this — these are small, isolated
regexes, easy to retune without touching the rest of the pipeline.
"""
import re
from pathlib import Path

from document_assistant.cargo.models import PolicySource


class PolicyFilenameParser:
    _POLICY_RE = re.compile(r"^\s*ГП\b", re.IGNORECASE)
    _DS_NUMBER_RE = re.compile(r"ДС\s*(?P<num>\d+)", re.IGNORECASE)
    _PARENTHETICAL_RE = re.compile(r"\(([^)]+)\)")
    _CLAUSE_NUMBER_RE = re.compile(r"п\.?\s*(\d+(?:\.\d+)*)", re.IGNORECASE)

    _POLICY_FOLDER_RE = re.compile(r"\bГП\b|ген\w*\s*полис", re.IGNORECASE)

    def parse_policy(self, file_path: str) -> PolicySource | None:
        """Recognizes the general policy file: name starts with "ГП"."""
        name = Path(file_path).stem
        if self._POLICY_RE.match(name):
            return PolicySource(kind="policy", file_path=file_path, raw_filename=name)
        return None

    def is_policy_folder_name(self, folder_name: str) -> bool:
        """Whether a subfolder holds the policy text — «текст ГП», «ГП 2026»,
        «текст ген. полиса». Excludes the ДС/Декларации siblings."""
        lowered = folder_name.lower()
        if lowered.startswith("дс") or "деклараци" in lowered:
            return False
        return bool(self._POLICY_FOLDER_RE.search(folder_name))

    def parse_ds(self, file_path: str) -> PolicySource | None:
        """Recognizes one ДС file: "ДС {number} (п.{clause}[, п.{clause}...])".

        Callers are expected to only call this on files already known to
        live in the ДС folder — the number pattern alone is the only
        requirement, no "ДС" keyword confirmation needed beyond that.
        """
        name = Path(file_path).stem
        num_match = self._DS_NUMBER_RE.search(name)
        if not num_match:
            return None

        clause_numbers: list[str] = []
        paren_match = self._PARENTHETICAL_RE.search(name)
        if paren_match:
            clause_numbers = self._CLAUSE_NUMBER_RE.findall(paren_match.group(1))

        return PolicySource(
            kind="ds",
            file_path=file_path,
            ds_number=int(num_match.group("num")),
            clause_numbers=clause_numbers,
            raw_filename=name,
        )


class DeclarationFilenameParser:
    """Extracts the declaration's sequence number from its file name.

    Default heuristic: the first run of 2-6 digits in the file name.
    """

    _NUM_RE = re.compile(r"(?<!\d)(\d{2,6})(?!\d)")

    def parse_number(self, file_path: str) -> str | None:
        name = Path(file_path).stem
        match = self._NUM_RE.search(name)
        return match.group(1) if match else None
