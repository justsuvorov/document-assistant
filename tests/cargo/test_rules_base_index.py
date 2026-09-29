"""Selecting relevant parts of the reconciliation rules base.

The base is injected into every chunk's prompt, so a 118 KB base across 61
shipments meant megabytes per run and 500s from the model gateway. Trimming
it is only safe if the sections that matter survive — a dropped rule stops
being applied silently, which is worse than a slow run.
"""
import pytest

from document_assistant.cargo.rules_base_index import RulesBaseIndex

RULES = "\n".join(
    [
        "3. Выгодоприобретатель: проверить организационно-правовую форму. " + "пояснение. " * 30,
        "7. Проверка перевозчика по перечню разрешённых перевозчиков. " + "пояснение. " * 30,
        "12. Страховая сумма: пересчёт валюты в евро по курсу. " + "пояснение. " * 30,
    ]
    + [f"{i}. Прочее правило номер {i}. " + "пояснение. " * 30 for i in range(20, 220)]
)


class TestRelevantSectionsSurvive:
    def setup_method(self):
        self.index = RulesBaseIndex(RULES)

    def _selected(self, query: str, budget: int = 6000) -> str:
        return self.index.retrieve(query, budget)

    def test_trims_to_budget(self):
        assert len(RULES) > 50_000            # база заведомо больше бюджета
        assert len(self._selected("перевозчик")) <= 6000

    @pytest.mark.parametrize("query,marker", [
        ("Перевозчик", "перечню разрешённых"),
        ("Страховая сумма", "пересчёт валюты"),
        ("Выгодоприобретатель", "организационно-правовую"),
    ])
    def test_field_name_selects_its_rule(self, query, marker):
        assert marker in self._selected(query)

    def test_all_three_fit_together(self):
        """A real query carries the whole field list at once."""
        selected = self._selected("Страхователь Выгодоприобретатель Страховая сумма Перевозчик")
        assert "перечню разрешённых" in selected
        assert "пересчёт валюты" in selected
        assert "организационно-правовую" in selected

    def test_matches_across_russian_inflections(self):
        """Query says «перевозчик», the rule says «перевозчика»/«перевозчиков»."""
        assert "перечню разрешённых" in self._selected("перевозчиками")


class TestScoringFix:
    """Sections split from numbered lines keep their whole text in the title
    and leave content empty; scoring content alone gave them all a flat zero
    and the ranking became arbitrary."""

    def test_title_only_sections_are_scored(self):
        index = RulesBaseIndex("1. Правило про перевозчика\n2. Правило про упаковку")
        section = index._sections[0]
        assert section.content.strip() == ""      # текст лежит в title

        from document_assistant.ai.context_builder import _tokenize
        score = index._score(f"{section.title}\n{section.content}", _tokenize("перевозчик"))

        assert score > 0
