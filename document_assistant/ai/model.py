import logging
import re
import time
import httpx
from abc import ABC, abstractmethod

from document_assistant.core.settings import settings

logger = logging.getLogger(__name__)


class AIModel(ABC):
    @abstractmethod
    def response(self, query: str) -> str:
        pass


# ── Qwen (OpenAI-compatible API) ──────────────────────────────────────────────

class QwenModel(AIModel):
    """Qwen via OpenAI-compatible API with automatic retry on service errors.

    Implements retry logic:
    - 503 / overloaded / connection errors — up to 3 retries with 5s delay
    - Empty response (ValueError) — up to 3 retries with 1s delay
    """

    retries = 3
    retry_delay = 5
    empty_response_retries = 3
    empty_response_delay = 1

    def __init__(self):
        self._api_url = settings.qwen_api_url
        self._model_name = settings.qwen_model_name
        self._client = httpx.Client(timeout=600, verify=False)  # 10 минут для больших промтов

    def response(self, query: str) -> str:
        for attempt in range(1, self.retries + 1):
            try:
                return self._call_api(query)
            except ValueError as exc:
                if self._is_empty_response(exc) and attempt < self.empty_response_retries:
                    logger.warning(
                        f"Qwen не вернул текст, "
                        f"попытка {attempt}/{self.empty_response_retries}, "
                        f"повтор через {self.empty_response_delay} сек")
                    time.sleep(self.empty_response_delay)
                    continue
                raise RuntimeError(f"Ошибка Qwen API: {exc}") from exc

            except httpx.TimeoutException as exc:
                if attempt < self.retries:
                    logger.warning(
                        f"Qwen таймаут (ReadTimeout), "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек")
                    time.sleep(self.retry_delay)
                    continue
                raise RuntimeError(f"Ошибка Qwen API: таймаут после {self.retries} попыток") from exc

            except httpx.HTTPStatusError as exc:
                if (exc.response.status_code in (503, 504) and attempt < self.retries):
                    logger.warning(
                        f"Qwen {exc.response.status_code}, "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек")
                    time.sleep(self.retry_delay)
                    continue
                raise RuntimeError(f"Ошибка Qwen API: {exc}") from exc

            except Exception as exc:
                if self._is_overload(exc) and attempt < self.retries:
                    logger.warning(
                        f"Qwen перегружен, "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек. Ошибка: {exc}")
                    time.sleep(self.retry_delay)
                    continue

                raise RuntimeError(f"Ошибка Qwen API: {exc}") from exc

        return "Сервис модели недоступен. Попробуйте позже."

    def _call_api(self, query: str) -> str:
        resp = self._client.post(
            self._api_url,
            json={
                "model": self._model_name,
                "prompt": query,
                "max_tokens": settings.qwen_max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["text"]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if not text:
            raise ValueError("Qwen не вернул текст")
        return text

    @staticmethod
    def _is_overload(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "503" in text
            or "504" in text
            or "unavailable" in text
            or "overloaded" in text
            or "connection" in text
            or "timeout" in text
        )

    @staticmethod
    def _is_empty_response(exc: Exception) -> bool:
        text = str(exc).lower()
        return "не вернул текст" in text or "no response" in text


# ── VSK AI (OpenAI-compatible /v1/chat/completions) ────────────────────────────

class VskAIModel(AIModel):
    """VSK AI via OpenAI-compatible chat API with automatic retry on service errors.

    Request format differs from QwenModel:
        POST {VSK_API_URL}
        Authorization: Bearer <VSK_API_KEY>
        {
            "model": "...",
            "messages": [{"role": "user", "content": "..."}],
            "thinking_token_budget": 1000,
            "max_tokens": 100000
        }

    Implements the same retry logic as QwenModel:
    - 503 / overloaded / connection errors — up to 3 retries with 5s delay
    - Empty response (ValueError) — up to 3 retries with 1s delay
    """

    retries = 5
    retry_delay = 5
    empty_response_retries = 3
    empty_response_delay = 1

    def __init__(self):
        self._api_url = settings.vsk_api_url
        self._api_key = settings.vsk_api_key.get_secret_value() if settings.vsk_api_key else ""
        self._model_name = settings.vsk_model_name
        self._client = httpx.Client(timeout=60, verify=False)

    def response(self, query: str) -> str:
        for attempt in range(1, self.retries + 1):
            try:
                return self._call_api(query)
            except ValueError as exc:
                if self._is_empty_response(exc) and attempt < self.empty_response_retries:
                    logger.warning(
                        f"VSK AI не вернул текст, "
                        f"попытка {attempt}/{self.empty_response_retries}, "
                        f"повтор через {self.empty_response_delay} сек")
                    time.sleep(self.empty_response_delay)
                    continue
                raise RuntimeError(f"Ошибка VSK AI API: {exc}") from exc

            except httpx.TimeoutException as exc:
                if attempt < self.retries:
                    logger.warning(
                        f"VSK AI таймаут (ReadTimeout), "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек")
                    time.sleep(self.retry_delay)
                    continue
                raise RuntimeError(f"Ошибка VSK AI API: таймаут после {self.retries} попыток") from exc

            except httpx.HTTPStatusError as exc:
                if (exc.response.status_code in (503, 504) and attempt < self.retries):
                    logger.warning(
                        f"VSK AI {exc.response.status_code}, "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек")
                    time.sleep(self.retry_delay)
                    continue
                raise RuntimeError(f"Ошибка VSK AI API: {exc}") from exc

            except Exception as exc:
                if self._is_overload(exc) and attempt < self.retries:
                    logger.warning(
                        f"VSK AI перегружен, "
                        f"попытка {attempt}/{self.retries}, "
                        f"повтор через {self.retry_delay} сек. Ошибка: {exc}")
                    time.sleep(self.retry_delay)
                    continue

                raise RuntimeError(f"Ошибка VSK AI API: {exc}") from exc

        return "Сервис модели недоступен. Попробуйте позже."

    def _call_api(self, query: str) -> str:
        resp = self._client.post(
            self._api_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model_name,
                "messages": [{"role": "user", "content": query}],
                "thinking_token_budget": settings.vsk_thinking_token_budget,
                "max_tokens": settings.vsk_max_tokens,
            },
        )
        resp.raise_for_status()
        return self._extract_text(resp.json())

    # Начало таблицы ответа — по нему достаём ответ, если он попал в reasoning.
    _TABLE_START = re.compile(r"^\|\s*Требование клиента", re.MULTILINE)

    @classmethod
    def _extract_text(cls, data: dict) -> str:
        """Текст ответа из chat/completions.

        vLLM с reasoning-parser кладёт рассуждение в ``message.reasoning_content``,
        а ``content`` бывает ``None``: модель не дошла до ответа (``finish_reason=length``)
        или парсер не нашёл конец рассуждения и отдал всё в reasoning.
        """
        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"VSK AI не вернул текст: в ответе нет choices, ключи={sorted(data)}")
        choice = choices[0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}

        content = message.get("content")
        if isinstance(content, list):  # формат «частей» OpenAI
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()

        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        logger.info(
            f"VSK AI ответ: finish_reason={finish}, "
            f"prompt_tokens={usage.get('prompt_tokens')}, "
            f"completion_tokens={usage.get('completion_tokens')}, "
            f"content={len(text)} симв., reasoning={len(reasoning)} симв.")
        if text:
            if finish == "length":
                logger.warning(f"VSK AI: ответ обрезан по max_tokens={settings.vsk_max_tokens} — "
                               "таблица может быть неполной")
            return text

        match = cls._TABLE_START.search(reasoning)
        if match:
            logger.warning("VSK AI: content пуст, таблица ответа найдена в reasoning_content — "
                           "берём её (reasoning-parser не отделил ответ от рассуждения)")
            return reasoning[match.start():].strip()

        hint = ""
        if finish == "length":
            hint = (f" — модель исчерпала max_tokens={settings.vsk_max_tokens}, не дойдя до ответа; "
                    "уменьшите VSK_THINKING_TOKEN_BUDGET или увеличьте VSK_MAX_TOKENS")
        elif finish == "content_filter":
            hint = " — ответ заблокирован фильтром содержимого на стороне VSK AI"
        raise ValueError(f"VSK AI не вернул текст (finish_reason={finish}, "
                         f"reasoning={len(reasoning)} симв.){hint}")

    @staticmethod
    def _is_overload(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "503" in text
            or "504" in text
            or "unavailable" in text
            or "overloaded" in text
            or "connection" in text
            or "timeout" in text
        )

    @staticmethod
    def _is_empty_response(exc: Exception) -> bool:
        text = str(exc).lower()
        return "не вернул текст" in text or "no response" in text


# ── Factory ───────────────────────────────────────────────────────────────────

class ModelFactory:
    """Create the AIModel instance for the configured provider (AI_PROVIDER)."""

    @staticmethod
    def create() -> AIModel:
        if settings.ai_provider == "vsk":
            model = VskAIModel()
            # Значение ключа не логируем никогда — только факт наличия.
            logger.info(
                f"Модель: VskAIModel (AI_PROVIDER={settings.ai_provider}), "
                f"имя модели '{settings.vsk_model_name or '<НЕ ЗАДАНО>'}', "
                f"эндпоинт {settings.vsk_api_url or '<НЕ ЗАДАН VSK_API_URL>'} (chat-формат), "
                f"ключ {'задан' if settings.vsk_api_key else 'НЕ ЗАДАН'}, "
                f"окно {settings.vsk_num_ctx} токенов, "
                f"max_tokens {settings.vsk_max_tokens}, "
                f"thinking_token_budget {settings.vsk_thinking_token_budget}, "
                f"температура {settings.ai_temperature}, "
                f"повторов при сбое {VskAIModel.retries}"
            )
            return model

        model = QwenModel()
        logger.info(
            f"Модель: QwenModel (AI_PROVIDER={settings.ai_provider or '<НЕ ЗАДАН>'}), "
            f"имя модели '{settings.qwen_model_name or '<НЕ ЗАДАНО>'}', "
            f"эндпоинт {settings.qwen_api_url or '<НЕ ЗАДАН QWEN_API_URL>'} (completions-формат), "
            f"ключ не используется, "
            f"окно {settings.qwen_num_ctx} токенов, "
            f"max_tokens {settings.qwen_max_tokens}, "
            f"температура {settings.ai_temperature}, "
            f"повторов при сбое {QwenModel.retries}"
        )
        return model
