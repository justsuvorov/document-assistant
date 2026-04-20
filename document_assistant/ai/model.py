import httpx
from abc import ABC, abstractmethod

import anthropic
from google import genai

from document_assistant.core.settings import settings


class AIModel(ABC):
    @abstractmethod
    def response(self, query: str) -> str:
        pass


# ── Gemini (cloud) ────────────────────────────────────────────────────────────

class GeminiModel(AIModel):
    def __init__(self):
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )
        self._config = genai.types.GenerateContentConfig(
            temperature=settings.ai_temperature,
            top_p=0.95,
            top_k=64,
            max_output_tokens=8192,
        )

    def response(self, query: str) -> str:
        try:
            result = self._client.models.generate_content(
                model=settings.model_name,
                contents=query,
                config=self._config,
            )
            if not result or not result.text:
                raise ValueError("Gemini не вернула текст (возможно, сработал фильтр)")
            return result.text.strip()
        except Exception as e:
            raise RuntimeError(f"Ошибка Gemini API: {e}") from e


# ── Anthropic Claude (cloud) ──────────────────────────────────────────────────

class AnthropicModel(AIModel):
    def __init__(self):
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )

    def response(self, query: str) -> str:
        try:
            message = self._client.messages.create(
                model=settings.anthropic_model_name,
                max_tokens=8192,
                temperature=settings.ai_temperature,
                messages=[{"role": "user", "content": query}],
            )
            return message.content[0].text.strip()
        except Exception as e:
            raise RuntimeError(f"Ошибка Anthropic API: {e}") from e


# ── Ollama (local Docker or remote GPU server) ────────────────────────────────

class OllamaModel(AIModel):
    """Connect to any Ollama instance via HTTP.

    Local Docker:      LLM_BASE_URL=http://ollama:11434
    Remote GPU server: LLM_BASE_URL=http://<server-ip>:11434
    """

    _ENDPOINT = "/api/chat"
    _TIMEOUT = 300.0  # large models on first load can take time

    def __init__(self, base_url: str, model_name: str, temperature: float):
        self._url = base_url.rstrip("/") + self._ENDPOINT
        self._model_name = model_name
        self._temperature = temperature

    def response(self, query: str) -> str:
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": query}],
            "stream": False,
            "options": {"temperature": self._temperature},
        }

        try:
            resp = httpx.post(self._url, json=payload, timeout=self._TIMEOUT)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama вернула ошибку {e.response.status_code}: {e.response.text}"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Ошибка подключения к Ollama: {e}") from e


# ── Factory ───────────────────────────────────────────────────────────────────

class ModelFactory:
    """Select and instantiate the right AIModel based on AI_PROVIDER.

    AI_PROVIDER=ollama     → OllamaModel  (local Docker or remote GPU server)
    AI_PROVIDER=gemini     → GeminiModel  (Google Gemini API)
    AI_PROVIDER=anthropic  → AnthropicModel (Anthropic Claude API)
    """

    _PROVIDERS = ("ollama", "gemini", "anthropic")

    @staticmethod
    def create() -> AIModel:
        provider = settings.ai_provider

        if provider == "ollama":
            return OllamaModel(
                base_url=settings.llm_base_url,
                model_name=settings.llm_model_name,
                temperature=settings.ai_temperature,
            )
        if provider == "gemini":
            return GeminiModel()
        if provider == "anthropic":
            return AnthropicModel()

        raise ValueError(
            f"Неизвестный AI_PROVIDER='{provider}'. "
            f"Допустимые значения: {ModelFactory._PROVIDERS}"
        )
