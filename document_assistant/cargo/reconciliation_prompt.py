from pathlib import Path

from document_assistant.ai.promt_builders import NormativeBaseLoader


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

    def build(self, rules_matrix_block: str, special_conditions: str, source_text: str) -> str:
        try:
            return self._template.format(
                role=self._role,
                reconciliation_logic=self._reconciliation_logic,
                rules_matrix=rules_matrix_block,
                special_conditions=special_conditions,
                source_text=source_text,
            )
        except KeyError as e:
            raise ValueError(f"Ошибка в шаблоне RECONCILIATION_PROMPT_TEMPLATE: отсутствует ключ {e}")
