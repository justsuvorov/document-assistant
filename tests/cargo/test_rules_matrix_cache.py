import time
from pathlib import Path

from document_assistant.cargo.models import PolicyClause, PolicySource, RulesMatrix
from document_assistant.cargo.rules_matrix_cache import RulesMatrixCache


def _make_source(path: Path, content: str = "content") -> PolicySource:
    path.write_text(content, encoding="utf-8")
    return PolicySource(kind="policy", file_path=str(path))


class TestFingerprint:
    def setup_method(self):
        self.cache = RulesMatrixCache()

    def test_stable_for_same_files(self, tmp_path: Path):
        f = tmp_path / "policy.txt"
        source = _make_source(f)
        fp1 = self.cache.fingerprint([source])
        fp2 = self.cache.fingerprint([source])
        assert fp1 == fp2

    def test_changes_when_file_modified(self, tmp_path: Path):
        f = tmp_path / "policy.txt"
        source = _make_source(f)
        fp1 = self.cache.fingerprint([source])

        time.sleep(0.01)
        f.write_text("changed content", encoding="utf-8")
        fp2 = self.cache.fingerprint([source])

        assert fp1 != fp2

    def test_changes_when_file_added(self, tmp_path: Path):
        f1 = tmp_path / "policy.txt"
        source1 = _make_source(f1)
        fp1 = self.cache.fingerprint([source1])

        f2 = tmp_path / "ds1.txt"
        source2 = _make_source(f2)
        fp2 = self.cache.fingerprint([source1, source2])

        assert fp1 != fp2

    def test_independent_of_list_order(self, tmp_path: Path):
        f1 = tmp_path / "policy.txt"
        f2 = tmp_path / "ds1.txt"
        source1 = _make_source(f1)
        source2 = _make_source(f2)

        fp_ab = self.cache.fingerprint([source1, source2])
        fp_ba = self.cache.fingerprint([source2, source1])

        assert fp_ab == fp_ba


class TestSaveLoad:
    def setup_method(self):
        self.cache = RulesMatrixCache()

    def test_round_trip(self, tmp_path: Path):
        matrix = RulesMatrix(
            policy_folder=str(tmp_path),
            fingerprint="abc123",
            built_at="2026-08-18T00:00:00+00:00",
            clauses=[
                PolicyClause(
                    clause_id="3.2",
                    clause_title="Объект страхования",
                    effective_text="Оборудование",
                    source_label="Ген. полис",
                    source_file="policy.docx",
                ),
            ],
        )
        self.cache.save(str(tmp_path), matrix)

        loaded = self.cache.load(str(tmp_path))

        assert loaded is not None
        assert loaded.fingerprint == "abc123"
        assert len(loaded.clauses) == 1
        assert loaded.clauses[0].clause_id == "3.2"
        assert loaded.clauses[0].effective_text == "Оборудование"

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert self.cache.load(str(tmp_path)) is None

    def test_cache_file_created_next_to_folder(self, tmp_path: Path):
        matrix = RulesMatrix(policy_folder=str(tmp_path), fingerprint="abc")
        path = self.cache.save(str(tmp_path), matrix)
        assert path == tmp_path / RulesMatrixCache.FILENAME
        assert path.exists()
