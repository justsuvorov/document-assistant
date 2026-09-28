"""Выбор AI-провайдера по AI_PROVIDER.

Смысл тестов: класс модели обращается к полям Settings напрямую, и если поля
нет (как было с vsk_* после добавления VskAIModel), падение случается только
в рантайме воркера — в кластере, на живой сессии. Здесь это ловится сразу.
"""

import pytest

from document_assistant.ai.model import ModelFactory, QwenModel, VskAIModel
from document_assistant.core.settings import settings


class TestModelFactory:
    def test_vsk_provider_creates_vsk_model(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_provider", "vsk")
        assert isinstance(ModelFactory.create(), VskAIModel)

    @pytest.mark.parametrize("provider", ["qwen", "ollama", ""])
    def test_other_providers_fall_back_to_qwen(self, monkeypatch, provider):
        monkeypatch.setattr(settings, "ai_provider", provider)
        assert isinstance(ModelFactory.create(), QwenModel)


class TestProviderSettingsExist:
    """Поля, которые читают классы моделей, обязаны быть объявлены в Settings."""

    @pytest.mark.parametrize(
        "field",
        [
            "vsk_api_url",
            "vsk_api_key",
            "vsk_model_name",
            "vsk_max_tokens",
            "vsk_thinking_token_budget",
            "vsk_num_ctx",
        ],
    )
    def test_vsk_fields_declared(self, field):
        assert hasattr(settings, field), (
            f"VskAIModel читает settings.{field}, но поля нет в Settings — "
            "в рантайме это AttributeError при первой же обработке"
        )

    @pytest.mark.parametrize(
        "field", ["qwen_api_url", "qwen_model_name", "qwen_max_tokens", "qwen_num_ctx"]
    )
    def test_qwen_fields_declared(self, field):
        assert hasattr(settings, field)
