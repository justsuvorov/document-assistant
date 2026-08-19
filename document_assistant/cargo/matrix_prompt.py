class MatrixPromptEngine:
    """Assemble the prompt that asks the LLM to extract clauses out of a single
    policy/ДС document. Narrower than PromptEngine: no normative base, no
    examples — just {role} and {source_text}.
    """

    def __init__(self, role: str, template: str):
        self._role = role
        self._template = template

    def build(self, source_text: str, clause_numbers: list[str] | None = None) -> str:
        """clause_numbers: when the source is a ДС whose file name already
        names the clauses it amends (e.g. "ДС 3 (п.9, п. 7)" -> ["9", "7"]),
        the prompt is narrowed to just those clauses instead of asking the
        LLM to find every clause in the document — ДС amendments typically
        only discuss the clauses they change, so this reduces hallucination
        risk and gives ClauseMerger a reliable clause NUMBER to key on.
        Appended after the template render rather than as a template
        placeholder, so existing MATRIX_PROMPT_TEMPLATE values don't need
        a {target_clauses} slot added to keep working.
        """
        try:
            prompt = self._template.format(role=self._role, source_text=source_text)
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне MATRIX_PROMPT_TEMPLATE: отсутствует ключ {e}")

        if clause_numbers:
            numbers = ", ".join(f"п.{n}" for n in clause_numbers)
            prompt += (
                f"\n\nВАЖНО: этот документ вносит изменения ТОЛЬКО в следующие пункты "
                f"генерального полиса: {numbers}. Извлеки актуальный текст именно для "
                f"этих пунктов (и только для них); в колонке «Пункт» укажи номер пункта "
                f"первым, например «9. Объект страхования»."
            )
        return prompt
