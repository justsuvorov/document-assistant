import re
from pathlib import Path


class NormativeBaseLoader:
    """Load insurance normative documents from a file or a directory.

    Supported plain-text formats (.md, .txt) are read directly.
    Structured formats (.xlsx, .docx, .pdf) are parsed via DataParser
    so the same markdown conversion pipeline is reused.
    """

    _PLAIN_TEXT = {".md", ".txt"}

    def load(self, path: str) -> str:
        if not path:
            return ""

        p = Path(path)
        if not p.exists():
            return ""

        if p.is_file():
            return self._read_file(p)

        if p.is_dir():
            return self._read_directory(p)

        return ""

    def _read_file(self, path: Path) -> str:
        if path.suffix.lower() in self._PLAIN_TEXT:
            return path.read_text(encoding="utf-8").strip()

        # Structured formats — reuse DataParser
        from document_assistant.core.parsers import DataParser
        try:
            return DataParser(str(path)).origin_data(str(path))
        except ValueError:
            return ""

    def _read_directory(self, directory: Path) -> str:
        from document_assistant.core.parsers import DataParser

        supported = set(DataParser._SUPPORTED) | self._PLAIN_TEXT
        parts = []

        for file in sorted(directory.iterdir()):
            if file.is_file() and file.suffix.lower() in supported:
                content = self._read_file(file)
                if content:
                    parts.append(f"### {file.stem}\n\n{content}")

        return "\n\n---\n\n".join(parts)


class PromptEngine:
    """Assemble the final LLM prompt from its parts.

    The template must contain the following placeholders:
        {role}           — system role / persona
        {normative_base} — loaded insurance normative documents
        {examples}       — few-shot examples (may be empty)
        {source_text}    — client request converted to markdown
    """

    def __init__(self, role: str, template: str, normative_base: str):
        """
        Args:
            role:           System role string (who the AI is).
            template:       Prompt template with {role}/{normative_base}/
                            {examples}/{source_text} placeholders.
            normative_base: Path (file or directory) to normative documents.
        """
        self._role = role
        self._template = template
        self._normative_base_content = NormativeBaseLoader().load(normative_base)

    def build(self, source_text: str, examples: list[str]) -> str:
        """Render the final prompt string.

        Args:
            source_text: Client document converted to markdown.
            examples:    List of formatted few-shot example strings.
        """
        examples_block = ""
        if examples:
            examples_block = "\n\n".join(
                f"### Пример {i + 1}\n{ex}" for i, ex in enumerate(examples)
            )

        try:
            return self._template.format(
                role=self._role,
                normative_base=self._normative_base_content,
                examples=examples_block,
                source_text=source_text,
            )
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне промпта: отсутствует ключ {e}")
