import re
import time
import httpx
from abc import ABC, abstractmethod

import anthropic
from google import genai
from google.genai import errors as genai_errors

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
            max_output_tokens=16384,
        )

    _MAX_RETRIES = 5
    _RETRY_DEFAULT = 60  # seconds to wait if retryDelay not parseable

    def response(self, query: str) -> str:
        for attempt in range(self._MAX_RETRIES):
            try:
                result = self._client.models.generate_content(
                    model=settings.model_name,
                    contents=query,
                    config=self._config,
                )
                if not result or not result.text:
                    raise ValueError("Gemini не вернула текст (возможно, сработал фильтр)")
                finish = getattr(result.candidates[0], 'finish_reason', 'unknown') if result.candidates else 'unknown'
                tokens_out = getattr(result.usage_metadata, 'candidates_token_count', '?') if result.usage_metadata else '?'
                print(f"[INFO] Gemini finish_reason={finish}, output_tokens={tokens_out}, chars={len(result.text)}", flush=True)
                return result.text.strip()
            except (genai_errors.ClientError, genai_errors.ServerError) as e:
                code = getattr(e, 'status_code', None) or getattr(e, 'code', None)
                is_retryable = code in (429, 503) or "429" in str(e) or "503" in str(e)
                if is_retryable and attempt < self._MAX_RETRIES - 1:
                    wait = self._parse_retry_delay(str(e)) + 5
                    print(f"[WARN] Gemini {code} — ожидание {wait}с (попытка {attempt + 1}/{self._MAX_RETRIES})", flush=True)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Ошибка Gemini API: {e}") from e
            except Exception as e:
                if attempt < self._MAX_RETRIES - 1 and any(s in str(e) for s in ("disconnected", "connection", "timeout")):
                    print(f"[WARN] Gemini сетевая ошибка — ожидание 10с (попытка {attempt + 1}/{self._MAX_RETRIES}): {e}", flush=True)
                    time.sleep(10)
                    continue
                raise RuntimeError(f"Ошибка Gemini API: {e}") from e
        raise RuntimeError("Gemini API: исчерпаны все попытки")

    @staticmethod
    def _parse_retry_delay(message: str) -> int:
        match = re.search(r"retryDelay['\"]:\s*['\"](\d+)s", message)
        return int(match.group(1)) if match else GeminiModel._RETRY_DEFAULT


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
    _TIMEOUT = 900.0  # large models on CPU can take 10+ min for long prompts

    def __init__(self, base_url: str, model_name: str, temperature: float, num_ctx: int):
        self._url = base_url.rstrip("/") + self._ENDPOINT
        self._model_name = model_name
        self._temperature = temperature
        self._num_ctx = num_ctx

    def response(self, query: str) -> str:
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": query}],
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_ctx": self._num_ctx,
            },
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
                num_ctx=settings.llm_num_ctx,
            )
        if provider == "gemini":
            return GeminiModel()
        if provider == "anthropic":
            return AnthropicModel()

        raise ValueError(
            f"Неизвестный AI_PROVIDER='{provider}'. "
            f"Допустимые значения: {ModelFactory._PROVIDERS}"
        )
