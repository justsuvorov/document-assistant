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

    def query(self) -> str:
        origin_data = self._parser.origin_data(self._request.file_path)
        text_content = self._text_encoder.prepared_data(origin_data)
        examples = self._build_references()

        return self._prompt_engine.build(
            source_text=text_content,
            examples=examples,
        )

    def _build_references(self) -> list[str]:
        """Load all example pairs from the examples folder."""
        return self._examples_loader.load(self._examples_path)
