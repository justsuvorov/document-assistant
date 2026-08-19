"""Parse policy/ДС/declaration metadata out of file names.

ADJUST ME: these patterns are best-effort defaults, not a confirmed customer
convention. Real policy/ДС/declaration file names should be used to tune the
regexes here before going to production — the rest of the pipeline does not
depend on their internals, only on the parsed result.
"""
import re
from datetime import date
from pathlib import Path

from document_assistant.cargo.models import PolicySource


class PolicyFilenameParser:
    """Classifies a file in the policy folder as the general policy or a ДС,
    and extracts the ДС number/effective date from its file name.
    """

    _DS_RE = re.compile(
        r"(?:ДС|доп\.?\s*согл\w*|дополнительн\w*\s+соглашени\w*|Addendum)"
        r"\s*(?:№|No\.?|N)?\s*(?P<num>\d+)"
        r"(?:\s*от\s*(?P<date>\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4}))?",
        re.IGNORECASE,
    )
    _POLICY_KEYWORDS = ("ген. полис", "ген.полис", "генеральный полис", "генерального полиса")
    _DATE_FORMATS = ("%d.%m.%Y", "%d-%m-%Y", "%d.%m.%y", "%d-%m-%y")

    def parse(self, file_path: str) -> PolicySource | None:
        name = Path(file_path).stem
        lowered = name.lower()

        ds_match = self._DS_RE.search(name)
        if ds_match:
            valid_from = self._parse_date(ds_match.group("date")) if ds_match.group("date") else None
            return PolicySource(
                kind="ds",
                file_path=file_path,
                ds_number=int(ds_match.group("num")),
                valid_from=valid_from,
                raw_filename=name,
            )

        if any(kw in lowered for kw in self._POLICY_KEYWORDS):
            return PolicySource(kind="policy", file_path=file_path, raw_filename=name)

        return None

    def _parse_date(self, raw: str) -> date | None:
        normalized = raw.replace("-", ".")
        parts = normalized.split(".")
        if len(parts) != 3:
            return None
        day, month, year = parts
        if len(year) == 2:
            year = "20" + year
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None


class DeclarationFilenameParser:
    """Extracts the declaration's sequence number from its file name.

    Default heuristic: the first run of 2-6 digits in the file name.
    """

    _NUM_RE = re.compile(r"(?<!\d)(\d{2,6})(?!\d)")

    def parse_number(self, file_path: str) -> str | None:
        name = Path(file_path).stem
        match = self._NUM_RE.search(name)
        return match.group(1) if match else None
