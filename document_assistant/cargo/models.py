from dataclasses import dataclass, field
from datetime import date


@dataclass
class PolicySource:
    """A file discovered in the policy folder: the general policy itself or one ДС."""
    kind: str                       # "policy" | "ds"
    file_path: str
    ds_number: int | None = None
    valid_from: date | None = None
    raw_filename: str = ""

    def sort_key(self) -> tuple:
        """Ascending precedence order: policy first, then ДС by (valid_from, ds_number)."""
        if self.kind == "policy":
            return (date.min, -1)
        return (self.valid_from or date.min, self.ds_number or 0)

    @property
    def label(self) -> str:
        if self.kind == "policy":
            return "Ген. полис"
        date_part = f" от {self.valid_from:%d.%m.%Y}" if self.valid_from else ""
        return f"ДС №{self.ds_number}{date_part}"


@dataclass
class PolicyClause:
    """One clause of the general policy with the currently-effective text."""
    clause_id: str
    clause_title: str
    effective_text: str
    source_label: str               # e.g. "Ген. полис" or "ДС №5 от 12.03.2025"
    source_file: str
    effective_from: date | None = None


@dataclass
class RulesMatrix:
    """Merged, currently-effective set of policy clauses (policy + all ДС)."""
    policy_folder: str
    fingerprint: str = ""
    built_at: str = ""
    clauses: list[PolicyClause] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        if not self.clauses:
            return ""
        lines = ["| Пункт | Актуальный текст/значение | Источник |", "|---|---|---|"]
        for c in self.clauses:
            label = f"{c.clause_id}: {c.clause_title}" if c.clause_title else c.clause_id
            lines.append(f"| {label} | {c.effective_text} | {c.source_label} |")
        return "\n".join(lines)


@dataclass
class ReconciliationRow:
    declaration_ref: str            # "200" или "200/1"
    field_name: str
    matched_policy_clause: str
    result: str                     # "совпадает" | "не совпадает" | "не знаю"
    comment: str


@dataclass
class ReconciliationReport:
    declaration_number: str
    rows: list[ReconciliationRow] = field(default_factory=list)
    raw_text: str = ""

    @classmethod
    def merge(cls, reports: list["ReconciliationReport"]) -> "ReconciliationReport":
        """Signature matches InsuranceReport.merge(reports) so AIAssistantService
        can use either interchangeably via its injected report_merge callable."""
        declaration_number = reports[0].declaration_number if reports else ""
        rows = [row for r in reports for row in r.rows]
        raw_text = "\n\n---\n\n".join(r.raw_text for r in reports if r.raw_text)
        return cls(declaration_number=declaration_number, rows=rows, raw_text=raw_text)
