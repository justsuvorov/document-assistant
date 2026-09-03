from dataclasses import dataclass, field


@dataclass
class PolicySource:
    """A file discovered for the policy folder: the general policy itself
    (filename starts with "ГП") or one ДС from the "ДС" subfolder (filename
    like "ДС 3 (п.9, п. 7)" — the parenthetical part names the clause
    numbers this ДС amends).
    """
    kind: str                             # "policy" | "ds"
    file_path: str
    ds_number: int | None = None
    clause_numbers: list[str] = field(default_factory=list)   # e.g. ["9", "7"], only for kind="ds"
    raw_filename: str = ""

    def sort_key(self) -> tuple:
        """Ascending precedence order: policy first, then ДС by ds_number."""
        if self.kind == "policy":
            return (-1,)
        return (self.ds_number or 0,)

    @property
    def label(self) -> str:
        if self.kind == "policy":
            return "Ген. полис"
        clauses_part = f" (п.{', п.'.join(self.clause_numbers)})" if self.clause_numbers else ""
        return f"ДС {self.ds_number}{clauses_part}"


@dataclass
class PolicyClause:
    """One clause of the general policy with the currently-effective text."""
    clause_id: str
    clause_title: str
    effective_text: str
    source_label: str               # e.g. "Ген. полис" or "ДС 3 (п.9, п. 7)"
    source_file: str


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
    result: str                     # "совпадает" | "не совпадает"
    comment: str
    # Set when the verdict contradicts its own comment (see result_consistency)
    needs_review: bool = False


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
