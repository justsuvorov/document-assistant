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


class TestPolicyAsFolder:
    """The policy may be filed inside a folder («текст ГП») rather than as a
    loose "ГП ..." document in the policy folder root."""

    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def test_finds_policy_inside_tekst_gp_folder(self, tmp_path: Path):
        gp_dir = tmp_path / "текст ГП"
        gp_dir.mkdir()
        _touch(gp_dir / "Договор страхования грузов.docx")

        sources = self.scanner.scan(str(tmp_path))

        assert [s.kind for s in sources] == ["policy"]
        assert sources[0].file_path == str(gp_dir / "Договор страхования грузов.docx")

    def test_ds_and_declarations_folders_are_not_mistaken_for_policy(self, tmp_path: Path):
        (tmp_path / "Декларации").mkdir()
        ds_dir = tmp_path / "ДС"
        ds_dir.mkdir()
        _touch(ds_dir / "ДС 1 (п.9).docx")

        sources = self.scanner.scan(str(tmp_path))

        assert [s.kind for s in sources] == ["ds"]

    def test_loose_gp_file_still_preferred_when_present(self, tmp_path: Path):
        _touch(tmp_path / "ГП главный.docx")
        gp_dir = tmp_path / "текст ГП"
        gp_dir.mkdir()
        _touch(gp_dir / "другой.docx")

        sources = self.scanner.scan(str(tmp_path))

        assert sources[0].file_path == str(tmp_path / "ГП главный.docx")


class TestDsFolderTolerance:
    """The ДС folder is named by hand on a Windows share — the scanner must
    still find it when the name deviates from the exact «ДС» convention."""

    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def _layout(self, tmp_path: Path, folder_name: str, files: list[str]) -> Path:
        _touch(tmp_path / "ГП полис.docx")
        ds_dir = tmp_path / folder_name
        ds_dir.mkdir()
        for f in files:
            _touch(ds_dir / f)
        return ds_dir

    @pytest.mark.parametrize("folder_name", [
        "ДС",
        "\u0414\u0043",              # Latin "C" homoglyph
        "Доп. соглашения",
        "ДС (доп. соглашения)",
    ])
    def test_finds_ds_across_folder_name_variants(self, tmp_path: Path, folder_name):
        self._layout(tmp_path, folder_name, ["ДС №1 (п.9).docx"])

        sources = self.scanner.scan(str(tmp_path))

        ds = [s for s in sources if s.kind == "ds"]
        assert len(ds) == 1
        assert ds[0].ds_number == 1

    def test_finds_ds_nested_in_per_ds_subfolders(self, tmp_path: Path):
        """Some clients file each ДС in its own subfolder."""
        _touch(tmp_path / "ГП полис.docx")
        nested = tmp_path / "ДС" / "ДС 2"
        nested.mkdir(parents=True)
        _touch(nested / "ДС №2 (п.5).docx")

        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert len(ds) == 1
        assert ds[0].ds_number == 2

    def test_declarations_folder_is_not_used_as_ds(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        decl = tmp_path / "Декларации"
        decl.mkdir()
        _touch(decl / "ДС 1 (п.9).docx")   # decoy

        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert ds == []

    def test_resolve_ds_folder_is_quiet_by_default(self, tmp_path: Path, capsys):
        """The carrier-list lookup reuses this resolution; only the scan pass
        should log, otherwise every warning appears twice."""
        _touch(tmp_path / "ГП полис.docx")
        self.scanner.resolve_ds_folder(str(tmp_path))
        assert capsys.readouterr().out == ""


class TestDsInPerAgreementSubfolders:
    """Real client layout: each ДС in its own folder, with attachments beside
    it. Taking every file turned 14 ДС into 27 sources and sent a лист
    согласования to the LLM as if it were the agreement.
    """

    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def _client_layout(self, tmp_path: Path) -> None:
        _touch(tmp_path / "ГП (рефрижераторный риск).docx")
        ds = tmp_path / "ДС"
        ds.mkdir()
        for folder, files in {
            "ДС 1 (п.5, п.11.9, п.18.2.19)": [
                "ДС - 1.docx", "ЛС к ДС 1.xls", "data2.xls",
                "ДС - 1_llm_debug.md", "ДС - 1_llm_output.json",
            ],
            "ДС 2 (п.7)": ["ДС - 2.docx", "ЛС к ДС 2.xls"],
            "ДС 3 (п.9, п.12)": ["ДС - 3.docx", "Согласование БКС.docx"],
        }.items():
            d = ds / folder
            d.mkdir()
            for f in files:
                _touch(d / f)

    def test_one_source_per_ds_not_per_file(self, tmp_path: Path):
        self._client_layout(tmp_path)
        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]
        assert [s.ds_number for s in ds] == [1, 2, 3]

    def test_agreement_document_is_chosen_over_attachments(self, tmp_path: Path):
        self._client_layout(tmp_path)
        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]
        assert [Path(s.file_path).name for s in ds] == ["ДС - 1.docx", "ДС - 2.docx", "ДС - 3.docx"]

    def test_clause_numbers_come_from_the_folder_name(self, tmp_path: Path):
        """The file is «ДС - 1.docx» — only the folder names the clauses, and
        a Path.stem read of it would chop «.19)» off as an extension."""
        self._client_layout(tmp_path)
        ds = {s.ds_number: s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"}
        assert ds[1].clause_numbers == ["5", "11.9", "18.2.19"]
        assert ds[3].clause_numbers == ["9", "12"]

    def test_soglasovanie_attachment_is_not_taken_as_body(self, tmp_path: Path):
        self._client_layout(tmp_path)
        ds = {s.ds_number: s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"}
        assert "Согласование" not in Path(ds[3].file_path).name


class TestFlatDsFolderDeduplication:
    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def test_attachment_beside_flat_ds_file_is_skipped(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        ds = tmp_path / "ДС"
        ds.mkdir()
        _touch(ds / "ДС 1 (п.9).docx")
        _touch(ds / "ЛС к ДС 1.xls")

        found = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert len(found) == 1
        assert Path(found[0].file_path).name == "ДС 1 (п.9).docx"

    def test_duplicate_numbers_collapse_to_one_source(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        ds = tmp_path / "ДС"
        ds.mkdir()
        _touch(ds / "ДС 1 (п.9).docx")
        _touch(ds / "ДС 1 копия.docx")

        found = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert len(found) == 1

    def test_generated_artifacts_are_not_reported_as_skipped(self, tmp_path: Path, capsys):
        _touch(tmp_path / "ГП полис.docx")
        ds = tmp_path / "ДС"
        ds.mkdir()
        _touch(ds / "ДС 1 (п.9).docx")
        _touch(ds / "ДС 1 (п.9)_llm_debug.md")
        _touch(ds / "ДС 1 (п.9)_llm_output.json")

        self.scanner.scan(str(tmp_path))

        assert "_llm_debug.md" not in capsys.readouterr().out


class TestOfficeLockFiles:
    """«~$ДС - 1.docx» is created by Word while a document is open. It has a
    .docx extension and a ДС-looking name, so it was picked as the agreement
    body and crashed the run with PackageNotFoundError."""

    def setup_method(self):
        self.scanner = PolicyFolderScanner()

    def test_lock_file_not_chosen_as_ds_body(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        d = tmp_path / "ДС" / "ДС 3 (п.5)"
        d.mkdir(parents=True)
        _touch(d / "~$ДС - 1.docx")
        _touch(d / "ДС - 3.docx")

        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert Path(ds[0].file_path).name == "ДС - 3.docx"

    def test_folder_with_only_a_lock_file_yields_no_ds(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        d = tmp_path / "ДС" / "ДС 3 (п.5)"
        d.mkdir(parents=True)
        _touch(d / "~$ДС - 1.docx")

        ds = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert ds == []

    def test_lock_file_not_chosen_as_policy(self, tmp_path: Path):
        _touch(tmp_path / "~$ГП полис.docx")
        _touch(tmp_path / "ГП полис.docx")

        sources = self.scanner.scan(str(tmp_path))

        assert Path(sources[0].file_path).name == "ГП полис.docx"

    def test_lock_file_in_flat_ds_folder_is_ignored(self, tmp_path: Path):
        _touch(tmp_path / "ГП полис.docx")
        ds = tmp_path / "ДС"
        ds.mkdir()
        _touch(ds / "~$ДС 1 (п.9).docx")
        _touch(ds / "ДС 1 (п.9).docx")

        found = [s for s in self.scanner.scan(str(tmp_path)) if s.kind == "ds"]

        assert len(found) == 1
        assert Path(found[0].file_path).name == "ДС 1 (п.9).docx"
