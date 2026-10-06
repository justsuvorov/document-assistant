"""Заполнение шаблона по ID: части таблицы → модель → проверка → запись."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from document_assistant.ai.model import AIModel
from document_assistant.ai.preprocessor import ProcessingTask
from document_assistant.core.settings import settings
from document_assistant.filling.answers import AnswerParser, AnswerValidator
from document_assistant.filling.models import ParsedTemplate
from document_assistant.filling.prompt import FillPromptBuilder
from document_assistant.filling.reader import TemplateReader
from document_assistant.filling.writer import TemplateAnswerWriter
from document_assistant.services.base import ProcessingService

logger = logging.getLogger(__name__)

MODE = "by_id"


class TemplateFillService:
    """Реализует тот же контракт, что и ``AIAssistantService``:
    ``result()`` → ``{"request_id", "user_name", "output_file"}``, артефакты
    ``*_llm_output.json`` и ``*_llm_debug.md`` рядом с исходником.

    Если в шаблоне не нашлось ни одной строки с ID (нет таблицы требований),
    работа передаётся ``fallback()`` — старому пути. Он создаётся лениво:
    сборка заново парсит нормативную базу, и без нужды делать это незачем.
    """

    def __init__(
        self,
        task: ProcessingTask,
        ai_model: AIModel,
        prompt_builder: FillPromptBuilder,
        fallback: Callable[[], ProcessingService],
        reader: TemplateReader | None = None,
        writer: TemplateAnswerWriter | None = None,
    ):
        self._task = task
        self._model = ai_model
        self._prompts = prompt_builder
        self._fallback = fallback
        self._reader = reader or TemplateReader()
        self._writer = writer or TemplateAnswerWriter()
        self._parser = AnswerParser()

    def result(self, max_chunks_override: int = 0) -> dict:
        source = Path(self._task.file_path)
        template = self._reader.read(source)
        if not template.rows:
            logger.warning("В шаблоне нет строк-требований — обработка старым способом")
            return self._fallback().result(max_chunks_override=max_chunks_override)

        chunks = self._reader.chunks(template, settings.llm_batch_size)
        limit = max_chunks_override if max_chunks_override > 0 else settings.llm_max_chunks
        if limit > 0:
            chunks = chunks[:limit]
        logger.info(f"Заполнение по ID: строк {len(template.rows)}, частей {len(chunks)}, "
                    f"листов {len(template.tables)}")

        validator = AnswerValidator(template.by_id())
        summaries: list[str] = []
        log_chunks: list[dict] = []
        for i, (table_md, ids) in enumerate(chunks, 1):
            logger.info(f"Часть {i}/{len(chunks)}: {len(ids)} строк ({ids[0]}…{ids[-1]})")
            raw = self._model.response(self._prompts.build(table_md))
            answers, summary = self._parser.parse(raw)
            ok, bad = validator.add(answers, set(ids))
            missing = len(ids) - sum(1 for r in ids if r in validator.accepted)
            logger.info(f"Часть {i}/{len(chunks)}: ответов {len(answers)}, принято {ok}, "
                        f"отброшено {bad}, без ответа {missing}")
            if summary:
                summaries.append(summary)
            log_chunks.append({"index": i, "ids": ids, "raw_response": raw,
                               "rows_parsed": len(answers), "accepted": ok, "rejected": bad})

        self._log_totals(template, validator)
        self._save_artifacts(source, log_chunks, validator)

        output = source.parent / f"{source.stem}_ответ.xlsx"
        self._writer.write(source, output, template, validator.accepted, "\n\n".join(summaries))
        return {
            "request_id": self._task.request_id,
            "user_name": self._task.user_name,
            "output_file": str(output),
        }

    @staticmethod
    def _log_totals(template: ParsedTemplate, validator: AnswerValidator) -> None:
        total = len(template.rows)
        filled = len(validator.accepted)
        reasons = Counter(r.reason for r in validator.rejected)
        logger.info(f"Итог по ID: заполнено {filled}/{total}, «Не обработано» {total - filled}, "
                    f"отброшено ответов {len(validator.rejected)} {dict(reasons) or ''}".rstrip())
        for r in validator.rejected:
            logger.debug(f"Отброшен {r.answer.row_id} ({r.reason}): {r.answer.requirement[:100]!r}")

    def _save_artifacts(self, source: Path, chunks: list[dict], validator: AnswerValidator) -> None:
        payload = {
            "mode": MODE,
            "file_path": str(source),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "provider": settings.ai_provider,
            "chunks": chunks,
            "rejected": [{"id": r.answer.row_id, "reason": r.reason,
                          "requirement": r.answer.requirement} for r in validator.rejected],
        }
        debug = "\n\n---\n\n".join(
            f"## Часть {c['index']} — {c['ids'][0]}…{c['ids'][-1]}, принято {c['accepted']}, "
            f"отброшено {c['rejected']}\n\n{c['raw_response']}" for c in chunks)
        try:
            source.with_name(source.stem + "_llm_output.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            source.with_name(source.stem + "_llm_debug.md").write_text(debug, encoding="utf-8")
        except Exception as e:
            logger.debug(f"Не удалось сохранить артефакты: {e}")

    @classmethod
    def rebuild_from_payload(cls, payload: dict, file_path: str, task: ProcessingTask) -> dict:
        """Пересобрать отчёт из сохранённого JSON без вызова модели."""
        source = Path(file_path)
        template = TemplateReader().read(source)
        validator = AnswerValidator(template.by_id())
        parser = AnswerParser()
        summaries = []
        for chunk in payload["chunks"]:
            answers, summary = parser.parse(chunk["raw_response"])
            validator.add(answers, set(chunk["ids"]))
            if summary:
                summaries.append(summary)
        cls._log_totals(template, validator)
        output = source.parent / f"{source.stem}_ответ.xlsx"
        TemplateAnswerWriter().write(source, output, template, validator.accepted, "\n\n".join(summaries))
        return {"request_id": task.request_id, "user_name": task.user_name, "output_file": str(output)}
