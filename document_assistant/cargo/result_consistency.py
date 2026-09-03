import re

from document_assistant.cargo.models import ReconciliationRow

MATCH = "совпадает"
MISMATCH = "не совпадает"

# Phrases that mean the comment is describing a DIFFERENCE. Checked only when
# the model reported "совпадает" — a contradiction worth flagging, since a
# reviewer reading the status column alone would otherwise miss it.
_MISMATCH_MARKERS = (
    "не совпад",
    "отличает",
    "отлича",
    "расхожд",
    "несоответств",
    "не соответств",
    "разн",
    "вместо",
    "не указан",
    "отсутств",
    "не найден",
)

# "не совпадает" contains "не совпад" — strip the status echo before scanning
# so a comment that merely restates the verdict isn't read as a contradiction.
_STATUS_ECHO_RE = re.compile(r"^\s*(не\s+совпадает|совпадает)\s*[.:,–—-]?\s*", re.IGNORECASE)


def normalize_status(raw: str) -> str:
    """Collapse the model's free-form verdict onto the two values the response
    form allows. Anything not recognizable as a positive match is treated as
    a mismatch — a wrong "не совпадает" costs a reviewer one glance, a wrong
    "совпадает" can let a real discrepancy through."""
    value = " ".join(raw.lower().split()).strip(" .!")
    if not value:
        return MISMATCH
    if value.startswith("не "):
        return MISMATCH
    if value.startswith(MATCH):
        return MATCH
    return MISMATCH


def comment_contradicts_match(comment: str) -> bool:
    stripped = _STATUS_ECHO_RE.sub("", comment or "")
    lowered = stripped.lower()
    return any(marker in lowered for marker in _MISMATCH_MARKERS)


def apply(rows: list[ReconciliationRow], declaration_ref: str) -> list[ReconciliationRow]:
    """Normalize each row's verdict and flag rows whose comment contradicts a
    "совпадает" verdict.

    Why this exists: reviewers reported rows marked "совпадает" whose comment
    plainly described differing values. The model is also instructed against
    this in the prompt, but the instruction alone is not enforceable — this
    pass makes the contradiction visible deterministically instead of relying
    on the reviewer to read every comment.

    The verdict is NOT silently rewritten: the row is marked for review and
    logged, so a human decides. Silently flipping would hide model errors in
    the opposite direction.
    """
    for row in rows:
        row.result = normalize_status(row.result)
        if row.result == MATCH and comment_contradicts_match(row.comment):
            row.needs_review = True
            print(
                f"[WARN] {declaration_ref}: поле «{row.field_name}» помечено «совпадает», "
                f"но комментарий указывает на расхождение — строка помечена на проверку. "
                f"Комментарий: {row.comment[:160]}",
                flush=True,
            )
    return rows
