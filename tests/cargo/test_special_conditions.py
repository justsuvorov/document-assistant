from pathlib import Path

from document_assistant.cargo.special_conditions import SpecialConditionsLoader
from document_assistant.core.settings import settings


class TestSpecialConditionsLoader:
    def test_no_files_returns_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(settings, "special_conditions_global_path", "")
        loader = SpecialConditionsLoader()
        assert loader.load(str(tmp_path)) == ""

    def test_loads_explicit_client_path(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(settings, "special_conditions_global_path", "")
        client_file = tmp_path / "conditions.txt"
        client_file.write_text("Клиент X: особый порядок уведомления", encoding="utf-8")

        loader = SpecialConditionsLoader()
        result = loader.load(str(tmp_path), explicit_path=str(client_file))

        assert "особый порядок уведомления" in result
        assert "Особые условия клиента" in result

    def test_discovers_client_file_by_keyword(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(settings, "special_conditions_global_path", "")
        client_file = tmp_path / "Особые условия клиента.txt"
        client_file.write_text("Нюанс сопровождения", encoding="utf-8")

        loader = SpecialConditionsLoader()
        result = loader.load(str(tmp_path))

        assert "Нюанс сопровождения" in result

    def test_loads_global_and_client_together(self, tmp_path: Path, monkeypatch):
        global_file = tmp_path / "global.txt"
        global_file.write_text("Общее правило для всех клиентов", encoding="utf-8")
        monkeypatch.setattr(settings, "special_conditions_global_path", str(global_file))

        client_file = tmp_path / "client.txt"
        client_file.write_text("Правило только для этого клиента", encoding="utf-8")

        loader = SpecialConditionsLoader()
        result = loader.load(str(tmp_path), explicit_path=str(client_file))

        assert "Общее правило для всех клиентов" in result
        assert "Правило только для этого клиента" in result
        assert result.index("Общее правило") < result.index("Правило только")
