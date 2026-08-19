from document_assistant.ai.preprocessor import Preprocessor


class DeclarationPreprocessor(Preprocessor):
    """Turns one declaration's pre-computed line-item chunks into full
    reconciliation prompts — the AIAssistantService-facing half of
    DocumentPreprocessor's role in the DMS pipeline.

    Chunking/classification happens one level up in
    CargoReconciliationService rather than inside this class, because the
    SAME classification result (single vs. multi-row) is also needed to
    construct the matching ReconciliationPostProcessor and to report
    type/line_items in the API response — those must exist before
    AIAssistantService.result() runs, so they can't be discovered by this
    preprocessor as a side effect of its own .queries() call.
    """

    def __init__(self, chunks: list[str], prompt_engine, rules_matrix_block: str, special_conditions_text: str):
        self._chunks = chunks
        self._prompt_engine = prompt_engine
        self._rules_matrix_block = rules_matrix_block
        self._special_conditions_text = special_conditions_text

    def queries(self) -> list[str]:
        return [
            self._prompt_engine.build(self._rules_matrix_block, self._special_conditions_text, chunk)
            for chunk in self._chunks
        ]


class ClauseExtractionPreprocessor(Preprocessor):
    """Turns one policy/ДС document's pre-computed chunks into clause-
    extraction prompts. Mirrors DeclarationPreprocessor's role for the
    rules-matrix-building step of the cargo pipeline.
    """

    def __init__(self, chunks: list[str], prompt_engine):
        self._chunks = chunks
        self._prompt_engine = prompt_engine

    def queries(self) -> list[str]:
        return [self._prompt_engine.build(source_text=chunk) for chunk in self._chunks]
