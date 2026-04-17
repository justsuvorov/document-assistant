from google import genai
from abc import ABC, abstractmethod
from document_assistant.core.settings import settings


class AIModel(ABC):
    @abstractmethod
    def response(self, query: str) -> str:
        """
        Метод должен принимать промпт и возвращать текстовый ответ.
        """
        pass


class GeminiModel(AIModel):
    def __init__(self):


        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value(),
                                    )

        self._generation_config = genai.types.GenerateContentConfig(
            temperature=settings.ai_temperature,
            top_p=0.95,
            top_k=64,
            max_output_tokens=4096,
        )

    def response(self, query: str) -> str:
        """
        Отправка запроса в Gemini и извлечение текста.
        """
        try:
            # Выполняем запрос
            response = self._client.models.generate_content(
                model=settings.model_name,
                contents=query,
                config=self._generation_config
            )

            # Проверка на наличие текста (защита от блокировок Safety Settings)
            if not response or not response.text:
                raise ValueError("Gemini не вернула текст (возможно, сработал фильтр контента)")

            return response.text.strip()

        except Exception as e:
            # Пробрасываем ошибку выше для обработки в main.py
            print( RuntimeError(f"Ошибка Gemini API: {str(e)}"))
            return query