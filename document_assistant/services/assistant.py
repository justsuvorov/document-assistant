import json
import time
from datetime import datetime, timezone
from pathlib import Path

from document_assistant.ai.model import AIModel
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.reports.report_models import InsuranceReport


class AIAssistantService:
    def __init__(
        self,
        preprocessor: DocumentPreprocessor,
        postprocessor: PostProcessor,
        ai_model: AIModel,
        report_export: ReportExport,
    ):
        self._preprocessor = preprocessor
        self._postprocessor = postprocessor
        self._model = ai_model
        self._report_export = report_export

    def result(self, max_chunks_override: int = 0) -> dict:
        queries = self._preprocessor.queries()
        limit = max_chunks_override if max_chunks_override > 0 else settings.llm_max_chunks
        if limit > 0:
            queries = queries[:limit]
        print(f"[INFO] Обработка {len(queries)} чанков", flush=True)

        reports = []
        debug_lines = []
        llm_chunks = []
        max_retries = 3

        for i, query in enumerate(queries, 1):
            print(f"[INFO] Чанк {i}/{len(queries)}...", flush=True)
            raw_response = None

            # Retry логика для каждого чанка
            for attempt in range(1, max_retries + 1):
                try:
                    raw_response = self._model.response(query)
                    report = self._postprocessor.report(raw_response)
                    reports.append(report)
                    debug_lines.append(f"## Чанк {i} — {len(report.rows)} строк\n\n{raw_response}")
                    llm_chunks.append({"index": i, "raw_response": raw_response, "rows_parsed": len(report.rows)})
                    break  # Успешно, выходим из retry loop
                except Exception as e:
                    print(
                        f"[WARN] Чанк {i}: ошибка на попытке {attempt}/{max_retries}: {e}",
                        flush=True,
                    )
                    if attempt < max_retries:
                        time.sleep(5)  # Пауза перед повтором
                        continue
                    else:
                        # После 3 попыток логируем что пропустили чанк и продолжаем
                        print(
                            f"[ERROR] Чанк {i} пропущен после {max_retries} попыток",
                            flush=True,
                        )
                        debug_lines.append(f"## Чанк {i} — ОШИБКА\n\nПропущен после {max_retries} попыток: {e}")
                        llm_chunks.append({"index": i, "raw_response": "", "rows_parsed": 0, "error": str(e)})
                        break

        # Сохраняем то что есть
        self._save_llm_debug(debug_lines)
        self._save_llm_json(llm_chunks)

        # Если есть хоть какие-то успешные результаты, возвращаем их
        if reports:
            report = InsuranceReport.merge(reports)
            return self._report_export.response(report)
        else:
            # Если вообще ничего не обработалось
            print("[ERROR] Не удалось обработать ни один чанк", flush=True)
            raise RuntimeError("Обработка не удалась: все чанки вернули ошибку")

    def _save_llm_debug(self, chunks: list[str]) -> None:
        try:
            file_path = Path(self._report_export._task.file_path)
            debug_path = file_path.with_name(file_path.stem + "_llm_debug.md")
            debug_path.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")
            print(f"[DEBUG] LLM ответы сохранены: {debug_path}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить LLM debug: {e}", flush=True)

    @staticmethod
    def rebuild_from_json(json_path: str, file_path: str, task: ProcessingTask) -> dict:
        """Собрать Excel из кэшированного JSON без вызова LLM.

        Raises ValueError если имя файла в JSON не совпадает с переданным file_path
        (защита от перепутанных файлов).
        """
        jp = Path(json_path)
        if not jp.exists():
            raise FileNotFoundError(f"JSON не найден: {json_path}")

        payload = json.loads(jp.read_text(encoding="utf-8"))

        # Сравниваем стемы (без пути и расширения) — пути могут отличаться контейнер/хост
        saved_stem = Path(payload["file_path"]).stem
        given_stem = Path(file_path).stem
        if saved_stem != given_stem:
            raise ValueError(
                f"Файл клиента не совпадает с JSON: "
                f"в кэше '{saved_stem}', передан '{given_stem}'. "
                "Проверьте, что json_path и file_path относятся к одному файлу."
            )

        postprocessor = PostProcessor()
        reports = []
        for chunk in payload["chunks"]:
            report = postprocessor.report(chunk["raw_response"])
            reports.append(report)

        merged = InsuranceReport.merge(reports)
        export = ReportExport(task)
        return export.response(merged)

    def _save_llm_json(self, chunks: list[dict]) -> None:
        try:
            file_path = Path(self._report_export._task.file_path)
            json_path = file_path.with_name(file_path.stem + "_llm_output.json")
            payload = {
                "file_path": str(file_path),
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "model": settings.anthropic_model_name if settings.ai_provider == "anthropic"
                         else settings.model_name if settings.ai_provider == "gemini"
                         else settings.llm_model_name,
                "provider": settings.ai_provider,
                "chunks": chunks,
            }
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[DEBUG] LLM JSON сохранён: {json_path}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Не удалось сохранить LLM JSON: {e}", flush=True)
