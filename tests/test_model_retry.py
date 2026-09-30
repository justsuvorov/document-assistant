"""Повторы при пустом ответе сервиса модели.

Регресс из боевого лога: сервис вернул `"content": null`, re.sub упал с
TypeError («expected string or bytes-like object, got 'NoneType'»), TypeError
не прошёл _is_overload — и цепочка из пяти попыток внутри модели оборвалась на
первой. Чанк спасали только внешние три попытки AIAssistantService.
"""
import pytest

from document_assistant.ai.model import VskAIModel
from document_assistant.services.assistant import AIAssistantService


class FakeResponse:
    def __init__(self, content):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class FakeClient:
    """Отдаёт заготовленные ответы по одному на вызов."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return FakeResponse(self._contents.pop(0))


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("document_assistant.ai.model.time.sleep", lambda _: None)


def _model(contents):
    model = VskAIModel()
    model._client = FakeClient(contents)
    return model


class TestNullContentIsRetried:
    def test_null_content_recovers_on_second_attempt(self, no_sleep):
        model = _model([None, "| таблица |"])

        assert model.response("q") == "| таблица |"
        assert model._client.calls == 2

    def test_null_content_uses_empty_response_retries(self, no_sleep):
        """Ровно та ветка, что и для пустой строки, — 3 попытки, не 1."""
        model = _model([None, None, "готово"])

        assert model.response("q") == "готово"
        assert model._client.calls == 3

    def test_exhausted_retries_raise_runtime_error_not_type_error(self, no_sleep):
        model = _model([None, None, None])

        with pytest.raises(RuntimeError) as exc:
            model.response("q")

        assert "не вернул текст" in str(exc.value)
        assert "NoneType" not in str(exc.value)

    def test_only_reasoning_without_answer_is_also_empty(self, no_sleep):
        """<think>…</think> и ничего больше — ответа нет."""
        model = _model(["<think>рассуждение</think>", "ответ"])

        assert model.response("q") == "ответ"
        assert model._client.calls == 2


class StubPreprocessor:
    def queries(self):
        return ["q1"]


class StubPostprocessor:
    class _Report:
        rows = ["r"]

    def report(self, raw_text, chunk_index=None):
        return self._Report()


class StubExport:
    def response(self, report):
        return {"ok": True}


class FlakyModel:
    def __init__(self, failures):
        self._failures = failures
        self.calls = 0

    def response(self, query):
        self.calls += 1
        if self.calls <= self._failures:
            raise RuntimeError("Ошибка VSK AI API: сервис недоступен")
        return "ответ"


class TestRetrySuccessIsLogged:
    def test_success_after_retry_is_visible_in_log(self, monkeypatch, capsys):
        """Без этой строки в логе остаётся одинокий WARN, и по логу нельзя
        отличить успешный повтор от потерянного чанка."""
        monkeypatch.setattr("document_assistant.services.assistant.time.sleep", lambda _: None)
        service = AIAssistantService(
            preprocessor=StubPreprocessor(),
            postprocessor=StubPostprocessor(),
            ai_model=FlakyModel(failures=1),
            report_export=StubExport(),
            report_merge=lambda reports: reports[0],
        )

        service.result()

        out = capsys.readouterr().out
        assert "ошибка на попытке 1/3" in out
        assert "успешно с попытки 2/3" in out

    def test_no_success_line_when_first_attempt_works(self, monkeypatch, capsys):
        monkeypatch.setattr("document_assistant.services.assistant.time.sleep", lambda _: None)
        service = AIAssistantService(
            preprocessor=StubPreprocessor(),
            postprocessor=StubPostprocessor(),
            ai_model=FlakyModel(failures=0),
            report_export=StubExport(),
            report_merge=lambda reports: reports[0],
        )

        service.result()

        assert "успешно с попытки" not in capsys.readouterr().out
