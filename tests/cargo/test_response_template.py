from pathlib import Path

from document_assistant.cargo.declaration_classifier import DeclarationType
from document_assistant.cargo.response_template import ResponseTemplate, ResponseTemplateResolver

TEMPLATES_DIR = Path(__file__).parents[2] / "document_assistant" / "cargo" / "templates"


class TestResponseTemplateLoading:
    def test_loads_prescribed_fields_from_vertical_form(self):
        template = ResponseTemplate.load(TEMPLATES_DIR / "reconciliation_form_vertical.xlsx")

        names = [f.field_name for f in template.fields]
        assert "Страхователь" in names
        assert "Перевозчик" in names
        assert len(template.fields) > 5

    def test_loads_prescribed_fields_from_horizontal_form(self):
        template = ResponseTemplate.load(TEMPLATES_DIR / "reconciliation_form_horizontal.xlsx")

        names = [f.field_name for f in template.fields]
        assert "Страхователь" in names
        assert any("Маршрут" in n for n in names)

    def test_field_carries_its_policy_clause_mapping(self):
        template = ResponseTemplate.load(TEMPLATES_DIR / "reconciliation_form_vertical.xlsx")
        field = next(f for f in template.fields if f.field_name == "Страхователь")
        assert field.policy_clause == "Страхователь"

    def test_prompt_block_is_a_markdown_table_of_fields(self):
        template = ResponseTemplate.load(TEMPLATES_DIR / "reconciliation_form_vertical.xlsx")
        block = template.to_prompt_block()

        assert block.startswith("| Наименование поля в декларации |")
        assert "Страхователь" in block
        # newlines inside a clause cell would break the markdown row
        assert all(line.count("\n") == 0 for line in block.split("\n"))


class TestTemplateSelection:
    def test_multi_declaration_uses_horizontal_psg_form(self):
        path = ResponseTemplateResolver.path_for(DeclarationType.MULTI)
        assert path.name == "reconciliation_form_horizontal.xlsx"

    def test_single_declaration_uses_vertical_form(self):
        path = ResponseTemplateResolver.path_for(DeclarationType.SINGLE)
        assert path.name == "reconciliation_form_vertical.xlsx"

    def test_env_override_wins_when_it_exists(self, tmp_path: Path, monkeypatch):
        from document_assistant.core.settings import settings
        custom = tmp_path / "custom_form.xlsx"
        custom.write_bytes((TEMPLATES_DIR / "reconciliation_form_vertical.xlsx").read_bytes())
        monkeypatch.setattr(settings, "reconciliation_template_vertical", str(custom))

        assert ResponseTemplateResolver.path_for(DeclarationType.SINGLE) == custom

    def test_falls_back_to_bundled_when_env_path_missing(self, tmp_path: Path, monkeypatch):
        from document_assistant.core.settings import settings
        monkeypatch.setattr(settings, "reconciliation_template_vertical", str(tmp_path / "nope.xlsx"))

        path = ResponseTemplateResolver.path_for(DeclarationType.SINGLE)
        assert path.name == "reconciliation_form_vertical.xlsx"
        assert path.exists()
