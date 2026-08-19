from pathlib import Path

from document_assistant.ai.promt_builders import NormativeBaseLoader
from document_assistant.core.settings import settings


class SpecialConditionsLoader:
    """Loads "особые условия" (deviations from the standard reconciliation
    process): a global file shared by all clients, and/or a per-client file
    living in the policy folder.

    Both are loaded when present and concatenated — the per-client text is
    labeled as taking precedence on conflict (in the prompt text itself, not
    programmatically, since resolving an actual conflict requires judgement
    the LLM should make case by case).
    """

    _CLIENT_KEYWORDS = ("особые условия", "особых условий")

    def __init__(self, loader: NormativeBaseLoader | None = None):
        self._loader = loader or NormativeBaseLoader()

    def load(self, policy_folder: str, explicit_path: str | None = None) -> str:
        global_text = self._loader.load(settings.special_conditions_global_path)

        client_path = explicit_path or self._discover(policy_folder)
        client_text = self._loader.load(client_path) if client_path else ""

        parts = []
        if global_text:
            parts.append(f"### Общие особые условия\n\n{global_text}")
        if client_text:
            parts.append(f"### Особые условия клиента (приоритет выше при конфликте)\n\n{client_text}")
        return "\n\n---\n\n".join(parts)

    def _discover(self, policy_folder: str) -> str | None:
        folder = Path(policy_folder)
        if not folder.is_dir():
            return None
        for file in sorted(folder.iterdir()):
            if not file.is_file():
                continue
            lowered = file.stem.lower()
            if any(kw in lowered for kw in self._CLIENT_KEYWORDS):
                return str(file)
        return None
