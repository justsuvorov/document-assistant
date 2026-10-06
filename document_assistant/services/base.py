"""Общий интерфейс обработки одной сессии.

Его реализуют ``AIAssistantService`` (старый путь: сопоставление ответа с
шаблоном по тексту) и ``TemplateFillService`` (заполнение по ID строк).
Воркер работает только с этим интерфейсом — какой путь выбран, решает
``build_dms_service`` по ``FILL_MODE``.
"""

from __future__ import annotations

from typing import Protocol


class ProcessingService(Protocol):
    def result(self, max_chunks_override: int = 0) -> dict:
        """Обработать файл клиента.

        Возвращает ``{"request_id", "user_name", "output_file"}``; рядом с
        исходником кладёт ``*_llm_output.json`` и ``*_llm_debug.md``.
        """
        ...
