"""
Reprocess Excel from cached LLM responses.

Reads uploads/client_llm_debug.md (cached chunk responses),
runs PostProcessor + ExcelReportWriter with the current code,
writes uploads/client_reprocess_ответ.xlsx.

Usage:
    python reprocess_from_debug.py
"""
from pathlib import Path
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.reports.report_models import InsuranceReport
from document_assistant.reports.writers import ExcelReportWriter

LLM_DEBUG  = Path("uploads/client_llm_debug.md")
SOURCE_XLS = Path("uploads/client.xlsx")
OUTPUT_XLS = Path("uploads/client_reprocess_ответ.xlsx")


def load_chunks(path: Path) -> list[str]:
    """Split the debug file into per-chunk raw LLM responses."""
    text = path.read_text(encoding="utf-8")
    sections = text.split("\n\n---\n\n")
    chunks = []
    for section in sections:
        lines = section.strip().splitlines()
        if not lines:
            continue
        # First line is "## Чанк N — X строк", skip it
        body = "\n".join(lines[1:]).strip()
        if body:
            chunks.append(body)
    return chunks


def main():
    print(f"Reading {LLM_DEBUG}")
    chunks = load_chunks(LLM_DEBUG)
    print(f"Found {len(chunks)} chunks")

    processor = PostProcessor()
    reports = []
    for i, raw in enumerate(chunks, 1):
        report = processor.report(raw)
        print(f"  Chunk {i}: {len(report.rows)} rows parsed")
        reports.append(report)

    merged = InsuranceReport.merge(reports)
    print(f"\nTotal rows after merge: {len(merged.rows)}")

    writer = ExcelReportWriter()
    out = writer.write(merged, OUTPUT_XLS, SOURCE_XLS)
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
