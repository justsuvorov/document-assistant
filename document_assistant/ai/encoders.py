import re
from abc import ABC, abstractmethod


class Encoder(ABC):
    @abstractmethod
    def prepared_data(self, source: str) -> str:
        pass


class TextEncoder(Encoder):
    """Normalize markdown text before sending to LLM.

    Removes noise that wastes tokens without adding information:
    repeated blank lines, trailing spaces on each line, non-printable
    characters, and BOM markers.
    """

    _MAX_CHARS = 60_000  # safety cap; adjust based on model context window

    def prepared_data(self, source: str) -> str:
        if not source:
            return ""

        text = source

        # Remove BOM and non-printable characters (keep newlines and tabs)
        text = text.replace("\ufeff", "")
        text = re.sub(r"[^\S\n\t ]+", " ", text)   # collapse exotic whitespace

        # Strip trailing spaces on every line
        text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

        # Collapse 3+ consecutive blank lines into 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        text = text.strip()

        # Hard cap to avoid exceeding context window
        if len(text) > self._MAX_CHARS:
            text = text[: self._MAX_CHARS]
            text += "\n\n[... документ обрезан из-за превышения максимального размера ...]"

        return text
