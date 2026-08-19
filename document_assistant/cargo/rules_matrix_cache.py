import hashlib
import json
from datetime import date
from pathlib import Path

from document_assistant.cargo.models import PolicyClause, PolicySource, RulesMatrix


class RulesMatrixCache:
    """Caches the built RulesMatrix next to the policy folder, keyed by a
    fingerprint of the source files (name + size + mtime). Mirrors the
    ``*_llm_output.json`` cache-next-to-file pattern used by AIAssistantService,
    but keyed by folder rather than by a single file.
    """

    FILENAME = "_matrix_cache.json"

    def fingerprint(self, sources: list[PolicySource]) -> str:
        parts = sorted(
            f"{Path(s.file_path).name}|{Path(s.file_path).stat().st_size}|{Path(s.file_path).stat().st_mtime_ns}"
            for s in sources
        )
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        return digest

    def load(self, policy_folder: str) -> RulesMatrix | None:
        path = self._cache_path(policy_folder)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        clauses = [
            PolicyClause(
                clause_id=c["clause_id"],
                clause_title=c["clause_title"],
                effective_text=c["effective_text"],
                source_label=c["source_label"],
                source_file=c["source_file"],
                effective_from=date.fromisoformat(c["effective_from"]) if c.get("effective_from") else None,
            )
            for c in payload.get("clauses", [])
        ]
        return RulesMatrix(
            policy_folder=policy_folder,
            fingerprint=payload.get("fingerprint", ""),
            built_at=payload.get("built_at", ""),
            clauses=clauses,
        )

    def save(self, policy_folder: str, matrix: RulesMatrix) -> Path:
        path = self._cache_path(policy_folder)
        payload = {
            "fingerprint": matrix.fingerprint,
            "built_at": matrix.built_at,
            "clauses": [
                {
                    "clause_id": c.clause_id,
                    "clause_title": c.clause_title,
                    "effective_text": c.effective_text,
                    "source_label": c.source_label,
                    "source_file": c.source_file,
                    "effective_from": c.effective_from.isoformat() if c.effective_from else None,
                }
                for c in matrix.clauses
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _cache_path(self, policy_folder: str) -> Path:
        return Path(policy_folder) / self.FILENAME
