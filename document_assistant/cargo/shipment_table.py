"""Locate the shipment table inside a declaration and split it per shipment.

A declaration is not a bare table: it carries a title, policy metadata
(Страхователь, № ген. полиса, период), a two-level column header, the
shipment rows, and a signature block. Splitting every markdown table row —
what the generic DocumentChunker does — turns a 2-shipment declaration into
15 LLM calls, 13 of them on junk rows that produce nothing usable.

This module finds the «№ п/п» table and treats ONLY its sequence-numbered
rows as shipments. Each emitted chunk keeps the document's preamble and
header so the model can still reconcile document-level fields
(Страхователь, период, № полиса) while looking at one shipment.

Classification and splitting share this one implementation on purpose: when
they were separate heuristics they disagreed, and the report ended up with
per-junk-row groups (200/1 … 200/15) for a two-shipment declaration.
"""
import re

from document_assistant.cargo.text_norm import fold

_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$")
_SEQUENCE_RE = re.compile(r"^\d{1,4}\.?$")
_ITEM_HEADER_MARKER = "п/п"

# A genuine column header names several columns; a stray «№ п/п договора»
# label row in a vertical form has only the label and its value.
_MIN_HEADER_CELLS = 3


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _filled(cells: list[str]) -> int:
    return sum(1 for c in cells if c)


def find_shipment_rows(text: str) -> tuple[int | None, list[int]]:
    """Return (header line index, shipment line indices) for the «№ п/п» table.

    Returns (None, []) when the document has no such table — i.e. it is a
    single-shipment (vertical) declaration.
    """
    lines = text.splitlines()

    header_idx = None
    pp_col = None
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line.strip()) or _SEPARATOR_RE.match(line.strip()):
            continue
        cells = _cells(line)
        if _filled(cells) < _MIN_HEADER_CELLS:
            continue
        for col, cell in enumerate(cells):
            if _ITEM_HEADER_MARKER in fold(cell).replace(" ", ""):
                header_idx, pp_col = i, col
                break
        if header_idx is not None:
            break

    if header_idx is None:
        return None, []

    shipment_idx = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not _TABLE_ROW_RE.match(line) or _SEPARATOR_RE.match(line):
            continue
        cells = _cells(lines[i])
        if pp_col < len(cells) and _SEQUENCE_RE.match(cells[pp_col]):
            shipment_idx.append(i)

    return header_idx, shipment_idx


def split_by_shipment(text: str) -> list[str]:
    """One chunk per shipment row, each keeping the document preamble and the
    table header. Returns a single whole-document chunk when there is no
    multi-shipment table."""
    header_idx, shipment_idx = find_shipment_rows(text)
    if header_idx is None or len(shipment_idx) < 2:
        return [text]

    lines = text.splitlines()
    # Preamble + header (+ any sub-header rows before the first shipment),
    # so each chunk still carries Страхователь / № полиса / period.
    context = lines[:shipment_idx[0]]
    return ["\n".join(context + [lines[i]]) for i in shipment_idx]
