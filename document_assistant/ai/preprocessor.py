import re
from dataclasses import dataclass
from pathlib import Path

from document_assistant.ai.encoders import Encoder
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser


@dataclass
class ProcessingTask:
    request_id: int
    file_path: str
    user_name: str = None
    priority: int = 0


class DocumentChunker:
    """Split a parsed document into logical chunks.

    Strategy (tried in order):
    1. Numbered sections — lines matching ``^\\d+\\.\\s`` (e.g. "1. Программа ...").
       Only the section body is kept; the preamble (general terms) is dropped
       to keep prompts focused on service data.
    2. Markdown headings — lines starting with ``#``.
    3. Fallback — the whole document as one chunk.
    """

    _NUMBERED = re.compile(r"^\d+\.\s")

    def split(self, text: str) -> list[str]:
        if not text.strip():
            return []

        chunks = self._split_numbered(text)
        if len(chunks) > 1:
            return chunks

        chunks = self._split_headings(text)
        if len(chunks) > 1:
            return chunks

        return [text.strip()]

    def _split_numbered(self, text: str) -> list[str]:
        lines = text.splitlines()
        section_starts = [i for i, ln in enumerate(lines) if self._NUMBERED.match(ln)]
        if not section_starts:
            return [text.strip()]

        chunks: list[str] = []
        for idx, start in enumerate(section_starts):
            end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
            body = "\n".join(lines[start:end]).strip()
            if body:
                chunks.append(body)

        return chunks

    def _split_headings(self, text: str) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("#") and current:
                chunk = "\n".join(current).strip()
                if chunk:
                    chunks.append(chunk)
                current = [line]
            else:
                current.append(line)
        if current:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
        return chunks


class ExamplesLoader:
    """Load few-shot examples from a directory.

    Expected folder layout::

        examples/
            001/
                client.xlsx        # client request (any supported format)
                response.docx      # specialist answer (any supported format)
            002/
                ...

    Each sub-directory must contain exactly two files.  Files are sorted
    alphabetically: the first becomes the *input* (client request), the
    second becomes the *output* (specialist answer).  Sub-directories with
    fewer or more than two files are skipped.
    """

    def load(self, examples_path: str) -> list[str]:
        if not examples_path:
            return []

        root = Path(examples_path)
        if not root.is_dir():
            return []

        examples = []
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue

            files = sorted(f for f in sub.iterdir() if f.is_file())
            if len(files) != 2:
                continue

            client_md = self._parse(files[0])
            response_md = self._parse(files[1])

            if client_md and response_md:
                examples.append(
                    f"**Запрос клиента:**\n{client_md}\n\n"
                    f"**Ответ специалиста:**\n{response_md}"
                )

        return examples

    @staticmethod
    def _parse(path: Path) -> str:
        try:
            return DataParser(str(path)).origin_data(str(path))
        except (ValueError, Exception):
            return ""


class Preprocessor:
    def query(self) -> str:
        pass


class DocumentPreprocessor(Preprocessor):
    """Read the client document and assemble the LLM query."""

    def __init__(
        self,
        data_parser: DataParser,
        request: ProcessingTask,
        encoder: Encoder,
        prompt_engine: PromptEngine,
        examples_path: str,
    ):
        self._parser = data_parser
        self._request = request
        self._text_encoder = encoder
        self._prompt_engine = prompt_engine
        self._examples_loader = ExamplesLoader()
        self._examples_path = examples_path
        self._chunker = DocumentChunker()

    def queries(self) -> list[str]:
        """Return one prompt per document chunk (no examples, full normative base)."""
        origin_data = self._parser.origin_data(self._request.file_path)
        text_content = self._text_encoder.prepared_data(origin_data)
        chunks = self._chunker.split(text_content)

        self._save_debug(text_content, chunks)

        return [
            self._prompt_engine.build(source_text=chunk, examples=[])
            for chunk in chunks
        ]

    def query(self) -> str:
        """Legacy single-query interface (no chunking)."""
        origin_data = self._parser.origin_data(self._request.file_path)
        text_content = self._text_encoder.prepared_data(origin_data)
        examples = self._build_references()
        return self._prompt_engine.build(source_text=text_content, examples=examples)

    def _save_debug(self, text_content: str, chunks: list[str]) -> None:
        base = Path(self._request.file_path).with_suffix("")
        debug_path = Path(str(base) + "_debug.md")

        # Also dump the normative base index
        norm_index = self._prompt_engine._norm_index
        norm_sections = norm_index._sections

        lines = [
            f"# DEBUG: parsed document ({len(chunks)} chunks)\n",
            "---\n",
            f"## Normative base ({norm_index.section_count} sections, "
            f"{len(norm_index.full_text)} chars)\n",
        ]
        for i, sec in enumerate(norm_sections[:5], 1):
            lines.append(f"\n### Norm section {i}: {sec.title[:80]}\n\n{sec.content[:500]}\n")
        if len(norm_sections) > 5:
            lines.append(f"\n... и ещё {len(norm_sections) - 5} разделов\n")

        lines += [
            "\n---\n",
            f"## Client document chunks ({len(chunks)})\n",
        ]
        for i, chunk in enumerate(chunks, 1):
            lines.append(f"\n### Chunk {i}\n\n{chunk[:800]}\n")
        try:
            debug_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"[DEBUG] {len(chunks)} чанков сохранено: {debug_path}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить: {e}", flush=True)

    def _build_references(self) -> list[str]:
        return self._examples_loader.load(self._examples_path)
