from dataclasses import dataclass, field


@dataclass
class ReportRow:
    client_requirement: str
    program_coverage: str
    status: str        # "Есть" | "Нет" | "Частично"
    comment: str


@dataclass
class InsuranceReport:
    rows: list[ReportRow] = field(default_factory=list)
    summary: str = ""
    raw_text: str = ""  # original LLM output, kept as fallback
