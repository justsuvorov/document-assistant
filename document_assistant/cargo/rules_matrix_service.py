from document_assistant.ai.model import ModelFactory
from document_assistant.cargo.models import RulesMatrix
from document_assistant.cargo.policy_discovery import PolicyFolderScanner
from document_assistant.cargo.rules_matrix_builder import RulesMatrixBuilder
from document_assistant.cargo.rules_matrix_cache import RulesMatrixCache


class RulesMatrixService:
    """Get-or-build entry point for the rules matrix, with folder-level caching."""

    def __init__(
        self,
        scanner: PolicyFolderScanner | None = None,
        cache: RulesMatrixCache | None = None,
        builder: RulesMatrixBuilder | None = None,
    ):
        self._scanner = scanner or PolicyFolderScanner()
        self._cache = cache or RulesMatrixCache()
        self._builder = builder or RulesMatrixBuilder(model=ModelFactory.create())

    @classmethod
    def default(cls) -> "RulesMatrixService":
        return cls()

    def get_or_build(self, policy_folder: str, force_rebuild: bool = False) -> tuple[RulesMatrix, bool]:
        """Returns (matrix, cache_hit)."""
        sources = self._scanner.scan(policy_folder)
        if not sources:
            raise ValueError(f"В папке полиса не найдено ни ген.полиса, ни ДС: {policy_folder}")

        fingerprint = self._cache.fingerprint(sources)

        if not force_rebuild:
            cached = self._cache.load(policy_folder)
            if cached is not None and cached.fingerprint == fingerprint:
                return cached, True

        matrix = self._builder.build(policy_folder, sources)
        matrix.fingerprint = fingerprint
        self._cache.save(policy_folder, matrix)
        return matrix, False
