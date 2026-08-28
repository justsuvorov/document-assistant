"""Сборка AIAssistantService.

Раньше эта функция жила в main.py. Вынесена сюда, потому что теперь её
использует и HTTP-слой, и воркер — иначе получился бы циклический импорт
(main → worker → main). Сама композиция объектов не изменилась.
"""

from __future__ import annotations

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import ModelFactory
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService


def build_dms_service(
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
                num_ctx=settings.qwen_num_ctx,
            ),
            examples_path=settings.examples_path,
        ),
        postprocessor=PostProcessor(),
        ai_model=ModelFactory.create(),
        report_export=ReportExport(task),
    )
