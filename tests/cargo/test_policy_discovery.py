from pathlib import Path

import pytest

from document_assistant.cargo.policy_discovery import PolicyFolderScanner


def _touch(path: Path, content: str = "x") -> None:
    path.write_text(content, encoding="utf-8")


class TestPolicyFolderScanner:
    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def test_default_layout_policy_file_plus_ds_subfolder(self, tmp_path: Path):
        _touch(tmp_path / "ГП страхования грузов.docx")
        ds_dir = tmp_path / "ДС"
        ds_dir.mkdir()
        _touch(ds_dir / "ДС 2 (п.5).docx")
        _touch(ds_dir / "ДС 1 (п.9).docx")

        sources = self.scanner.scan(str(tmp_path))

        assert [s.kind for s in sources] == ["policy", "ds", "ds"]
        assert [s.ds_number for s in sources[1:]] == [1, 2]  # ascending, not filesystem order

    def test_ds_clause_numbers_parsed(self, tmp_path: Path):
        _touch(tmp_path / "ГП.docx")
        ds_dir = tmp_path / "ДС"
        ds_dir.mkdir()
        _touch(ds_dir / "ДС 3 (п.9, п. 7).docx")

        sources = self.scanner.scan(str(tmp_path))

        ds = next(s for s in sources if s.kind == "ds")
        assert ds.clause_numbers == ["9", "7"]

    def test_no_ds_subfolder_is_fine_policy_only(self, tmp_path: Path):
        _touch(tmp_path / "ГП.docx")
        sources = self.scanner.scan(str(tmp_path))
        assert [s.kind for s in sources] == ["policy"]

    def test_ignores_unsupported_extensions(self, tmp_path: Path):
        _touch(tmp_path / "ГП.docx")
        ds_dir = tmp_path / "ДС"
        ds_dir.mkdir()
        _touch(ds_dir / "ДС 1 (п.9).zip")

        sources = self.scanner.scan(str(tmp_path))

        assert len(sources) == 1
        assert sources[0].kind == "policy"

    def test_nothing_found_raises_value_error(self, tmp_path: Path):
        with pytest.raises(ValueError):
            self.scanner.scan(str(tmp_path))

    def test_missing_policy_folder_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            self.scanner.scan(str(tmp_path / "missing"))


class TestOverrides:
    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def test_policy_file_override(self, tmp_path: Path):
        # Nothing named "ГП ..." in the folder at all — override must still work.
        override = tmp_path / "custom_policy_name.docx"
        _touch(override)

        sources = self.scanner.scan(str(tmp_path), policy_file_override=str(override))

        assert len(sources) == 1
        assert sources[0].kind == "policy"
        assert sources[0].file_path == str(override)

    def test_policy_file_override_missing_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            self.scanner.scan(str(tmp_path), policy_file_override=str(tmp_path / "missing.docx"))

    def test_ds_folder_override(self, tmp_path: Path):
        _touch(tmp_path / "ГП.docx")
        custom_ds_dir = tmp_path / "custom_ds_location"
        custom_ds_dir.mkdir()
        _touch(custom_ds_dir / "ДС 1 (п.9).docx")

        sources = self.scanner.scan(str(tmp_path), ds_folder_override=str(custom_ds_dir))

        ds_sources = [s for s in sources if s.kind == "ds"]
        assert len(ds_sources) == 1
        assert ds_sources[0].file_path == str(custom_ds_dir / "ДС 1 (п.9).docx")

    def test_ds_folder_override_missing_raises(self, tmp_path: Path):
        _touch(tmp_path / "ГП.docx")
        with pytest.raises(FileNotFoundError):
            self.scanner.scan(str(tmp_path), ds_folder_override=str(tmp_path / "missing_ds"))
