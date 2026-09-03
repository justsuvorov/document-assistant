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
from document_assistant.cargo.text_norm import fold


class PolicyFilenameParser:
    _POLICY_RE = re.compile(r"^\s*гп\b")
    # «ДС 1», «ДС №1», «ДС N1», «ДС_1», «ДС1», «Доп. соглашение 1», «ДС-1».
    # Applied to the folded name (see text_norm), so it is lowercase-only and
    # already immune to Latin/Cyrillic homoglyphs.
    _DS_NUMBER_RE = re.compile(
        r"(?:дс|доп\w*\.?\s*соглашени\w*)\s*[№n#\-_]?\s*(?P<num>\d+)"
    )
    _PARENTHETICAL_RE = re.compile(r"\(([^)]+)\)")
    _CLAUSE_NUMBER_RE = re.compile(r"п\.?\s*(\d+(?:\.\d+)*)")

    _POLICY_FOLDER_RE = re.compile(r"\bгп\b|ген\w*\.?\s*полис")
    _DS_FOLDER_RE = re.compile(r"^дс\b|^дс$|доп\w*\.?\s*соглашени")

    def parse_policy(self, file_path: str) -> PolicySource | None:
        """Recognizes the general policy file: name starts with "ГП"."""
        name = Path(file_path).stem
        if self._POLICY_RE.match(fold(name)):
            return PolicySource(kind="policy", file_path=file_path, raw_filename=name)
        return None

    def is_policy_folder_name(self, folder_name: str) -> bool:
        """Whether a subfolder holds the policy text — «текст ГП», «ГП 2026»,
        «текст ген. полиса». Excludes the ДС/Декларации siblings."""
        folded = fold(folder_name)
        if self.is_ds_folder_name(folder_name) or "деклараци" in folded:
            return False
        return bool(self._POLICY_FOLDER_RE.search(folded))

    def is_ds_folder_name(self, folder_name: str) -> bool:
        """Whether a subfolder holds the addenda — «ДС», «ДС (доп. соглашения)»,
        «Доп. соглашения». Matched on the folded name, so a Latin-"C" «ДC»
        typed by hand is still recognized."""
        return bool(self._DS_FOLDER_RE.search(fold(folder_name)))

    # Attachments that live beside a ДС but are not the agreement itself —
    # «ЛС к ДС 1» (лист согласования), approval sheets, carrier lists. They
    # carry the ДС number in their name, so without this they are picked up
    # as duplicate ДС and sent to the LLM as if they were the agreement.
    _AUXILIARY_MARKERS = (
        "лс к",
        "лист согласовани",
        "согласование",
        "согласовани",
        "перечень",
    )

    def is_auxiliary_name(self, name: str) -> bool:
        folded = fold(name)
        return any(marker in folded for marker in self._AUXILIARY_MARKERS)

    def parse_ds(self, file_path: str) -> PolicySource | None:
        """Recognizes one ДС file: "ДС {number} (п.{clause}[, п.{clause}...])".

        Callers are expected to only call this on files already known to
        live in the ДС folder — the number pattern alone is the only
        requirement, no "ДС" keyword confirmation needed beyond that.
        """
        return self._parse_ds_text(Path(file_path).stem, file_path)

    def parse_ds_folder(self, folder: Path) -> PolicySource | None:
        """Same, for a per-ДС subfolder («ДС 1 (п.5, п.11.9, п.18.2.19)»).

        Uses the folder's full name rather than Path.stem: a name like the
        above ends in ".19)", which stem would chop off as an extension and
        take the closing paren with it — leaving the clause list unparseable.
        """
        return self._parse_ds_text(folder.name, str(folder))

    def _parse_ds_text(self, name: str, path: str) -> PolicySource | None:
        folded = fold(name)
        num_match = self._DS_NUMBER_RE.search(folded)
        if not num_match:
            return None

        clause_numbers: list[str] = []
        paren_match = self._PARENTHETICAL_RE.search(folded)
        if paren_match:
            clause_numbers = self._CLAUSE_NUMBER_RE.findall(paren_match.group(1))

        return PolicySource(
            kind="ds",
            file_path=path,
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
