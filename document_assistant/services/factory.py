"""Сборка сервиса обработки сессии (оркестратор).

Раньше эта функция жила в main.py. Вынесена сюда, потому что теперь её
использует и HTTP-слой, и воркер — иначе получился бы циклический импорт
(main → worker → main). Путь обработки выбирается по FILL_MODE.
"""

from __future__ import annotations

import logging
from pathlib import Path

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import ModelFactory
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser
from document_assistant.core.settings import settings
from document_assistant.filling.prompt import FillPromptBuilder
from document_assistant.filling.service import TemplateFillService
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService
from document_assistant.services.base import ProcessingService

logger = logging.getLogger(__name__)


def _num_ctx() -> int:
    # Бюджет контекста берём у того провайдера, который реально будет вызван
    # (ModelFactory смотрит на тот же AI_PROVIDER): иначе при VSK промт
    # нарезался бы под окно Qwen.
    return settings.vsk_num_ctx if settings.ai_provider == "vsk" else settings.qwen_num_ctx


def build_dms_service(
    task: ProcessingTask, normative_base: str | None = None
) -> ProcessingService:
    """Выбрать путь обработки по FILL_MODE и формату файла.

    by_id работает только с .xlsx (нужны адреса строк шаблона); для Word/PDF
    и при FILL_MODE=legacy — старый AIAssistantService. Он же — запасной путь
    внутри by_id, если в шаблоне не нашлось строк-требований.
    """
    mode = settings.fill_mode.strip().lower()
    is_xlsx = Path(task.file_path).suffix.lower() == ".xlsx"
    if mode == "by_id" and is_xlsx:
        logger.info("Режим заполнения: by_id (ответ по ID строк шаблона)")
        return TemplateFillService(
            task=task,
            ai_model=ModelFactory.create(),
            prompt_builder=FillPromptBuilder(
                role=settings.ai_role,
                template=settings.ai_fill_prompt_template,
                normative_base=normative_base or settings.normative_base,
                num_ctx=_num_ctx(),
            ),
            fallback=lambda: _build_legacy(task, normative_base),
        )
    if mode not in ("by_id", "legacy"):
        logger.warning(f"FILL_MODE={settings.fill_mode!r} не распознан — используется legacy")
    logger.info(f"Режим заполнения: legacy ({'FILL_MODE=legacy' if is_xlsx else 'файл не .xlsx'})")
    return _build_legacy(task, normative_base)


def _build_legacy(
    task: ProcessingTask, normative_base: str | None = None
) -> AIAssistantService:
    """``normative_base`` — путь к нормативке этой сессии.

    Если пользователь загрузил свою базу, передаётся путь к скачанному из S3
    файлу; иначе берётся общая из settings. В десктопной версии загруженная
    база копировалась в общую папку — в многопользовательском режиме это
    означало бы, что один пользователь подменяет базу всем остальным.
    """
    return AIAssistantService(
        preprocessor=DocumentPreprocessor(
            data_parser=DataParser(file_path=task.file_path),
            request=task,
            encoder=TextEncoder(),
            prompt_engine=PromptEngine(
                role=settings.ai_role,
                template=settings.ai_prompt_template,
                normative_base=normative_base or settings.normative_base,
                num_ctx=_num_ctx(),
            ),
            examples_path=settings.examples_path,
        ),
        postprocessor=PostProcessor(),
        ai_model=ModelFactory.create(),
        report_export=ReportExport(task),
    )
