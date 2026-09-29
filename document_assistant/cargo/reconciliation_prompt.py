from pathlib import Path

from document_assistant.ai.promt_builders import NormativeBaseLoader
from document_assistant.cargo.rules_base_index import RulesBaseIndex
from document_assistant.core.settings import settings


class ReconciliationPromptEngine:
    """Assembles the prompt for reconciling one declaration (or one line item
    of a multi-row declaration) against the rules matrix.

    Template placeholders: {role} {reconciliation_logic} {rules_matrix}
    {special_conditions} {source_text}.

    RECONCILIATION_RULES_BASE (normative_base/ equivalent for this pipeline)
    is loaded once at construction — it's algorithm instructions ("which
    fields to compare and how"), not a program catalog, so unlike PromptEngine
    it does not need RAG/ContextBuilder retrieval in v1: expected to be small.
    """

    def __init__(self, role: str, template: str, rules_base_path: str):
        self._role = role
        self._template = template
        self._reconciliation_logic = NormativeBaseLoader().load(rules_base_path)

        # The base goes into EVERY chunk's prompt, so for a multi-shipment
        # declaration its size is multiplied by the number of shipments.
        # Above the budget we send only the sections relevant to the
        # declaration at hand instead of the whole file.
        self._budget = settings.reconciliation_rules_max_chars
        self._index: RulesBaseIndex | None = None
        if self._budget and len(self._reconciliation_logic) > self._budget:
            self._index = RulesBaseIndex(self._reconciliation_logic)
            print(
                f"[INFO] Логика сверки: {len(self._reconciliation_logic)} символов превышает "
                f"бюджет {self._budget} на один запрос — будут отбираться релевантные разделы "
                f"(всего разделов: {self._index.section_count})",
                flush=True,
            )

        if not rules_base_path:
            print("[INFO] Логика сверки (RECONCILIATION_RULES_BASE): путь не задан в .env", flush=True)
        elif not Path(rules_base_path).exists():
            print(
                f"[WARN] Логика сверки (RECONCILIATION_RULES_BASE): путь задан, но не найден — "
                f"{rules_base_path}",
                flush=True,
            )
        else:
            print(
                f"[INFO] Логика сверки (RECONCILIATION_RULES_BASE): загружено "
                f"{len(self._reconciliation_logic)} символов из {rules_base_path}",
                flush=True,
            )

    def _logic_for(self, source_text: str, template_fields_block: str = "") -> str:
        """Whole base when it fits the per-request budget, otherwise the
        sections most relevant to this declaration.

        The field list from the response form is part of the query: the rules
        are written about fields («Страхователь», «Перевозчик», «Страховая
        сумма»), so the field names match rule wording far better than the
        declaration's own values do.
        """
        if self._index is None:
            return self._reconciliation_logic
        query = f"{template_fields_block}\n{source_text}" if template_fields_block else source_text
        return self._index.retrieve(query, self._budget)

    def build(
        self,
        rules_matrix_block: str,
        special_conditions: str,
        source_text: str,
        template_fields_block: str = "",
        carrier_list_text: str = "",
    ) -> str:
        reconciliation_logic = self._logic_for(source_text, template_fields_block)
        try:
            prompt = self._template.format(
                role=self._role,
                reconciliation_logic=reconciliation_logic,
                rules_matrix=rules_matrix_block,
                special_conditions=special_conditions,
                source_text=source_text,
            )
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне RECONCILIATION_PROMPT_TEMPLATE: отсутствует ключ {e}")

        # Appended rather than added as template placeholders, so existing
        # RECONCILIATION_PROMPT_TEMPLATE values in deployed .env files keep
        # working without needing new {…} slots.
        if carrier_list_text:
            prompt += (
                "\n\n## ПЕРЕЧЕНЬ РАЗРЕШЁННЫХ ПЕРЕВОЗЧИКОВ (приложение к полису):\n"
                f"{carrier_list_text}\n"
                "Проверь, что перевозчик, заявленный в декларации, есть в этом перечне. "
                "Если перевозчика в перечне нет — это «не совпадает», укажи это в комментарии."
            )

        if template_fields_block:
            prompt += (
                "\n\n## ОБЯЗАТЕЛЬНЫЙ СПИСОК ПОЛЕЙ ДЛЯ ПРОВЕРКИ (форма ответа):\n"
                f"{template_fields_block}\n"
                "ВАЖНО: верни в таблице РОВНО эти строки, в этом же порядке, с этими же "
                "наименованиями полей — не добавляй свои поля и не пропускай указанные. "
                "Если поле в декларации отсутствует, всё равно верни строку и поясни это в комментарии."
            )

        prompt += (
            "\n\nВАЖНО о колонке «Результат проверки»: допустимы только значения "
            "«совпадает» или «не совпадает». Значение ОБЯЗАНО соответствовать комментарию: "
            "если в комментарии указано любое расхождение, отличие или несоответствие данных — "
            "результат «не совпадает». Ставь «совпадает» только когда данные действительно идентичны."
        )
        return prompt
