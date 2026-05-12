"""Context-window management with normative base retrieval.

Flow for each client chunk:
  1. Try to fit full normative base + chunk into the context window.
  2. If it doesn't fit — split the normative base into sections, score each
     section by keyword overlap with the chunk, and greedily pick the
     highest-scoring sections that still fit.
"""

import re
from typing import NamedTuple

from document_assistant.core.settings import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\b\w{3,}\b", re.UNICODE)
_NUMBERED = re.compile(r"^\d+\.\s", re.MULTILINE)
# ALL-CAPS Russian/Latin line that looks like a section header (5-100 chars, no lowercase)
_CAPS_HEADER = re.compile(r"^[А-ЯЁA-Z«»\s\-\(\)\/\.,:]{5,100}$")


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)}


# ── Normative base index ───────────────────────────────────────────────────────

class NormSection(NamedTuple):
    title: str
    content: str


class NormativeIndex:
    """Splits the normative base into sections and scores them by relevance.

    Splitting strategy (same priority as DocumentChunker):
    1. Numbered lines  ``^\\d+\\.\\s``
    2. Markdown headings ``#``
    3. Whole text as one section
    """

    def __init__(self, text: str):
        self._sections: list[NormSection] = self._split(text)
        self._full_text = text

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def full_text(self) -> str:
        return self._full_text

    @property
    def section_count(self) -> int:
        return len(self._sections)

    @property
    def MAX_SECTIONS(self) -> int:
        return settings.llm_max_sections

    def retrieve(self, query: str, budget_chars: int) -> str:
        """Return the most relevant sections that fit within budget_chars."""
        query_tokens = _tokenize(query)
        scored = [
            (sec, self._score(sec.content, query_tokens))
            for sec in self._sections
        ]
        scored.sort(key=lambda x: -x[1])

        selected: list[NormSection] = []
        used = 0
        for sec, _score in scored[: self.MAX_SECTIONS]:
            chunk_len = len(sec.title) + len(sec.content) + 4  # separators
            if used + chunk_len <= budget_chars:
                selected.append(sec)
                used += chunk_len

        # Restore original order
        order = {sec: i for i, sec in enumerate(self._sections)}
        selected.sort(key=lambda s: order[s])

        if not selected:
            # Nothing fits — return the first section truncated to budget
            first = self._sections[0]
            return (first.title + "\n" + first.content)[:budget_chars]

        parts = [
            f"{s.title}\n{s.content}" if s.title else s.content
            for s in selected
        ]
        return "\n\n---\n\n".join(parts)

    # ── private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _score(text: str, query_tokens: set[str]) -> float:
        text_tokens = _tokenize(text)
        if not text_tokens:
            return 0.0
        intersection = len(query_tokens & text_tokens)
        return intersection / (len(query_tokens | text_tokens) or 1)

    _MIN_SUBSECTIONS = 5  # require at least this many sub-sections after deep split

    def _split(self, text: str) -> list[NormSection]:
        sections = self._split_numbered(text)
        if len(sections) > 1:
            return self._deepen(sections)
        sections = self._split_headings(text)
        if len(sections) > 1:
            return self._deepen(sections)
        sections = self._split_caps(text)
        if len(sections) > 1:
            return self._deepen(sections)
        return [NormSection(title="", content=text.strip())]

    def _deepen(self, sections: list[NormSection]) -> list[NormSection]:
        """Split oversized sections further by paragraph headings."""
        result: list[NormSection] = []
        for sec in sections:
            if len(sec.content) < 5000:
                result.append(sec)
                continue
            sub = self._split_paragraph_headers(sec.content)
            if len(sub) >= self._MIN_SUBSECTIONS:
                for s in sub:
                    title = f"{sec.title} / {s.title}".strip(" /") if s.title else sec.title
                    result.append(NormSection(title=title, content=s.content))
            else:
                result.append(sec)
        return result

    @staticmethod
    def _split_numbered(text: str) -> list[NormSection]:
        lines = text.splitlines()
        starts = [i for i, ln in enumerate(lines) if _NUMBERED.match(ln)]
        if not starts:
            return []
        preamble = "\n".join(lines[: starts[0]]).strip()
        sections = []
        if preamble:
            sections.append(NormSection(title="", content=preamble))
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            body_lines = lines[start:end]
            title = body_lines[0].strip()
            body = "\n".join(body_lines[1:]).strip()
            sections.append(NormSection(title=title, content=body))
        return sections

    @staticmethod
    def _split_headings(text: str) -> list[NormSection]:
        sections: list[NormSection] = []
        current_title = ""
        current_body: list[str] = []
        for line in text.splitlines():
            if line.startswith("#"):
                if current_body:
                    sections.append(NormSection(
                        title=current_title,
                        content="\n".join(current_body).strip(),
                    ))
                current_title = line.lstrip("#").strip()
                current_body = []
            else:
                current_body.append(line)
        if current_body:
            sections.append(NormSection(
                title=current_title,
                content="\n".join(current_body).strip(),
            ))
        return sections

    @staticmethod
    def _split_caps(text: str) -> list[NormSection]:
        """Split by ALL-CAPS header lines (common in Russian insurance documents)."""
        lines = text.splitlines()
        # A header is an all-caps line preceded and followed by blank lines
        starts: list[int] = []
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped:
                continue
            if _CAPS_HEADER.match(stripped) and len(stripped.split()) >= 2:
                prev_blank = i == 0 or not lines[i - 1].strip()
                if prev_blank:
                    starts.append(i)

        if len(starts) < 2:
            return []

        sections: list[NormSection] = []
        preamble_end = starts[0]
        if preamble_end > 0:
            preamble = "\n".join(lines[:preamble_end]).strip()
            if preamble:
                sections.append(NormSection(title="", content=preamble))

        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            title = lines[start].strip()
            body = "\n".join(lines[start + 1:end]).strip()
            sections.append(NormSection(title=title, content=body))

        return sections

    @staticmethod
    def _split_paragraph_headers(text: str) -> list[NormSection]:
        """Split by lines that look like sub-section titles.

        Heuristic: a non-empty line that is preceded by a blank line,
        followed by a blank line or more content, starts with a capital
        letter, and is shorter than 150 chars (not a body paragraph).
        """
        lines = text.splitlines()
        n = len(lines)
        starts: list[int] = []

        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped or len(stripped) > 150:
                continue
            if not stripped[0].isupper():
                continue
            # Must be preceded by blank line (or be the first line)
            prev_blank = i == 0 or not lines[i - 1].strip()
            # Must be followed by non-blank content (actual section body)
            next_has_content = any(lines[j].strip() for j in range(i + 1, min(i + 4, n)))
            if prev_blank and next_has_content:
                starts.append(i)

        if len(starts) < 3:
            return []

        sections: list[NormSection] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else n
            title = lines[start].strip()
            body = "\n".join(lines[start + 1:end]).strip()
            if body:
                sections.append(NormSection(title=title, content=body))

        return sections


# ── Context builder ────────────────────────────────────────────────────────────

class ContextBuilder:
    """Decides how much of the normative base to include in the prompt.

    Steps:
    1. Build full prompt — if it fits in the context window, return it as-is.
    2. Otherwise compute how many chars are left for the normative base and
       ask ``NormativeIndex.retrieve()`` to fill that budget with the most
       relevant sections.
    """

    CHARS_PER_TOKEN = 3          # conservative for Russian text
    OUTPUT_RESERVE = 2048        # tokens reserved for model output

    def __init__(self, num_ctx: int, norm_index: NormativeIndex):
        self._max_chars = (num_ctx - self.OUTPUT_RESERVE) * self.CHARS_PER_TOKEN
        self._index = norm_index

    def build(
        self,
        template: str,
        role: str,
        examples: str,
        source_text: str,
    ) -> str:
        """Return a prompt that fits within the context window."""
        full_norm = self._index.full_text
        prompt = self._render(template, role, full_norm, examples, source_text)

        if len(prompt) <= self._max_chars:
            return prompt

        # How many chars can the normative base occupy?
        skeleton = self._render(template, role, "", examples, source_text)
        norm_budget = self._max_chars - len(skeleton)

        if norm_budget <= 0:
            print(
                "[WARN] Даже без нормативной базы промпт превышает контекст. "
                "Обрезаем source_text.",
                flush=True,
            )
            return prompt[: self._max_chars]

        retrieved = self._index.retrieve(source_text, norm_budget)
        fitted = self._render(template, role, retrieved, examples, source_text)

        tokens_est = len(fitted) // self.CHARS_PER_TOKEN
        sections_used = len([s for s in self._index._sections if s.content in retrieved])
        print(
            f"[INFO] Контекст: полная база не влезла → отобрано {sections_used} "
            f"разделов из {self._index.section_count}, ~{tokens_est} токенов",
            flush=True,
        )
        return fitted

    @staticmethod
    def _render(template, role, normative_base, examples, source_text) -> str:
        try:
            return template.format(
                role=role,
                normative_base=normative_base,
                examples=examples,
                source_text=source_text,
            )
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне промпта: отсутствует ключ {e}")
