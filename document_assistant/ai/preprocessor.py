from dataclasses import dataclass
from typing import List

from document_assistant.ai.encoders import Encoder
from document_assistant.ai.promt_builders import PromptEngine

from document_assistant.core.parsers import DataParser


@dataclass
class ProcessingTask:
    request_id: int
    file_path: str
    user_name: str = None
    priority: int = 0
    examples: str=None


class Preprocessor:
    def query(self):
        pass


class DocumentPreprocessor(Preprocessor):
    '''Class for reading origin document and preparing query for LLM model'''
    def __init__(self,
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
        self._examples_path = examples_path


    def query(self):
        '''Make full query for LLM model'''
        origin_data = self._parser.origin_data(self._request.file_path)
        text_content = self._text_encoder.prepared_data(origin_data["path"])
        references = self._build_references()

        return self._prompt_engine.build(
            source_text=text_content,
            context=references
        )

    def _build_references(self)->List[str]:
        '''Method for reading all files in examples folder. Return input-output text for promt builder'''
        pass
