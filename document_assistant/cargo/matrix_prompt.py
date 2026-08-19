class MatrixPromptEngine:
    """Assemble the prompt that asks the LLM to extract clauses out of a single
    policy/ДС document. Narrower than PromptEngine: no normative base, no
    examples — just {role} and {source_text}.
    """

    def __init__(self, role: str, template: str):
        self._role = role
        self._template = template

    def build(self, source_text: str) -> str:
        try:
            return self._template.format(role=self._role, source_text=source_text)
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне MATRIX_PROMPT_TEMPLATE: отсутствует ключ {e}")
