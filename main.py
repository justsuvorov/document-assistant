import sys
from pathlib import Path

# Весь лог пишется по-русски. Если stdout уходит не в консоль, а в файл или
# в пайп, Python берёт кодировку локали (cp1251), и первый же символ вне неё
# роняет запрос с UnicodeEncodeError — в собранном EXE это возвращало 500 на
# ровном месте. Переводим потоки в UTF-8 до того, как что-либо напечатано.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import ModelFactory
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask, DocumentChunker
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.cargo.carrier_list import CarrierListLocator
from document_assistant.cargo.declaration_classifier import DeclarationType, DeclarationTypeClassifier
from document_assistant.cargo.declaration_discovery import DeclarationDiscovery
from document_assistant.cargo.filename_parsing import DeclarationFilenameParser
from document_assistant.cargo.models import ReconciliationReport
from document_assistant.cargo.preprocessors import DeclarationPreprocessor
from document_assistant.cargo.reconciliation_postprocessor import ReconciliationPostProcessor
from document_assistant.cargo.reconciliation_prompt import ReconciliationPromptEngine
from document_assistant.cargo.reconciliation_writer import ReconciliationExcelWriter
from document_assistant.cargo.report_export import CargoReportExport
from document_assistant.cargo.response_template import ResponseTemplateResolver
from document_assistant.cargo.shipment_table import split_by_shipment
from document_assistant.cargo.rules_matrix_service import RulesMatrixService
from document_assistant.cargo.special_conditions import SpecialConditionsLoader
from document_assistant.core.parsers import DataParser
from document_assistant.core.pydantic_models import APIRequest, EstimateRequest, ReconcileRequest, RebuildRequest
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService

app = FastAPI()

def _build_service(request: APIRequest) -> AIAssistantService:
    task = ProcessingTask(
        request_id=request.request_id,
        file_path=request.file_path,
        user_name=request.user_name,
    )
    return AIAssistantService(
        preprocessor=DocumentPreprocessor(
            data_parser=DataParser(file_path=request.file_path),
            request=task,
            encoder=TextEncoder(),
            prompt_engine=PromptEngine(
                role=settings.ai_role,
                template=settings.ai_prompt_template,
                normative_base=settings.normative_base,
                num_ctx=settings.vsk_num_ctx if settings.ai_provider == "vsk" else settings.qwen_num_ctx,
            ),
            examples_path=settings.examples_path,
        ),
        postprocessor=PostProcessor(),
        ai_model=ModelFactory.create(),
        report_export=ReportExport(task),
    )


@app.post("/api/estimate")
def estimate(request: EstimateRequest):
    """Оценить количество чанков и время обработки без вызова LLM."""
    try:
        raw = DataParser(request.file_path).origin_data(request.file_path)
        encoded = TextEncoder().prepared_data(raw)
        chunks = DocumentChunker(batch_size=settings.llm_batch_size).split(encoded)
        chunk_count = len(chunks)
        return {
            "chunk_count": chunk_count,
            "estimated_seconds": chunk_count * 120,
            "total_chars": len(raw),
            "processed_chars": len(encoded),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/update")
def submit(request: APIRequest):
    ai = _build_service(request)
    result = ai.result(max_chunks_override=request.max_chunks)
    return JSONResponse(content=jsonable_encoder(result))


def _build_reconciliation_service(
    decl_path: str,
    request: ReconcileRequest,
    rules_matrix_block: str,
    prompt_engine: ReconciliationPromptEngine,
    special_conditions_text: str,
    carrier_list_text: str,
) -> tuple[AIAssistantService, DeclarationType, int]:
    """Builds one AIAssistantService for one declaration file — the cargo
    counterpart to _build_service() above. Classification happens here
    (not inside DeclarationPreprocessor) because ReconciliationPostProcessor
    also needs to know single-vs-multi before AIAssistantService.result() runs.
    """
    print(f"[INFO] Чтение декларации: {Path(decl_path).name}", flush=True)
    raw = DataParser(decl_path).origin_data(decl_path)
    text = TextEncoder().prepared_data(raw)
    print(
        f"[INFO]   прочитано {len(raw)} символов, после нормализации {len(text)}",
        flush=True,
    )
    decl_number = DeclarationFilenameParser().parse_number(decl_path) or "UNKNOWN"
    decl_type = DeclarationTypeClassifier().classify(text)
    multi = decl_type is DeclarationType.MULTI
    # Split per shipment row, not per markdown table row: the latter also
    # chunks the title, metadata and signature block into their own LLM calls.
    chunks = split_by_shipment(text) if multi else [text]

    template = ResponseTemplateResolver.for_type(decl_type)
    layout = "горизонтальная (ПСГ)" if multi else "вертикальная"
    print(
        f"[INFO] Декларация №{decl_number}: тип={decl_type.value}, "
        f"форма={layout}, строк перевозки={len(chunks)}",
        flush=True,
    )

    task = ProcessingTask(request_id=request.request_id, file_path=decl_path, user_name=request.user_name)
    service = AIAssistantService(
        preprocessor=DeclarationPreprocessor(chunks=chunks,
                                             prompt_engine=prompt_engine,
                                             rules_matrix_block=rules_matrix_block,
                                             special_conditions_text=special_conditions_text,
                                             template_fields_block=template.to_prompt_block(),
                                             carrier_list_text=carrier_list_text,
                                             ),
        postprocessor=ReconciliationPostProcessor(declaration_number=decl_number, multi=multi),
        ai_model=ModelFactory.create(),
        report_export=CargoReportExport(
            task,
            decl_number,
            ReconciliationExcelWriter(
                template=template, special_conditions_text=special_conditions_text,
            ),
        ),
        report_merge=ReconciliationReport.merge,
    )
    return service, decl_type, len(chunks)


@app.post("/api/reconcile")
def reconcile(request: ReconcileRequest):
    """Сверка деклараций с генеральным полисом и ДС."""
    print(f"[INFO] ═══ Сверка деклараций: {request.policy_folder} ═══", flush=True)
    try:
        matrix, cache_hit = RulesMatrixService.default().get_or_build(
            request.policy_folder,
            policy_file_override=request.policy_file_override,
            ds_folder_override=request.ds_folder_override,
            force_rebuild=request.force_rebuild_matrix,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    declaration_paths = DeclarationDiscovery.resolve(request.policy_folder, request.declaration_paths)
    if not declaration_paths:
        raise HTTPException(
            status_code=422,
            detail="Не найдено ни одной декларации для сверки (папка 'Декларации' пуста или не существует)",
        )
    print(f"[INFO] Деклараций к сверке: {len(declaration_paths)}", flush=True)
    for p in declaration_paths:
        print(f"[INFO]   - {Path(p).name}", flush=True)

    special_conditions_text = SpecialConditionsLoader().load(
        request.policy_folder, request.special_conditions_path,
    )

    carrier_list = CarrierListLocator().locate(
        request.policy_folder,
        ds_folder_override=request.ds_folder_override,
        policy_file_override=request.policy_file_override,
    )
    carrier_list_text = carrier_list.text if carrier_list else ""

    prompt_engine = ReconciliationPromptEngine(
        role=settings.reconciliation_ai_role,
        template=settings.reconciliation_prompt_template,
        rules_base_path=settings.reconciliation_rules_base,
    )
    rules_matrix_block = matrix.to_prompt_block()

    declarations_out = []
    for decl_path in declaration_paths:
        service, decl_type, chunk_count = _build_reconciliation_service(
            decl_path, request, rules_matrix_block, prompt_engine,
            special_conditions_text, carrier_list_text,
        )
        decl_result = service.result(max_chunks_override=request.max_chunks)
        decl_result["type"] = decl_type.value
        decl_result["line_items"] = chunk_count if decl_type is DeclarationType.MULTI else 1
        declarations_out.append(decl_result)

    print(
        f"[INFO] ═══ Сверка завершена: {len(declarations_out)} деклараций, "
        f"матрица правил — {len(matrix.clauses)} пунктов "
        f"({'из кэша' if cache_hit else 'построена заново'}) ═══",
        flush=True,
    )

    result = {
        "request_id": request.request_id,
        "user_name": request.user_name,
        "policy_folder": request.policy_folder,
        "matrix": {
            "clause_count": len(matrix.clauses),
            "fingerprint": matrix.fingerprint,
            "cache_hit": cache_hit,
        },
        "carrier_list": {
            "found": carrier_list is not None,
            "file": Path(carrier_list.file_path).name if carrier_list else None,
            "source": carrier_list.source_label if carrier_list else None,
        },
        "declarations": declarations_out,
    }
    return JSONResponse(content=jsonable_encoder(result))


@app.post("/api/rebuild")
def rebuild(request: RebuildRequest):
    """Собрать Excel из кэшированного LLM JSON без повторного вызова модели."""
    task = ProcessingTask(
        request_id=request.request_id,
        file_path=request.file_path,
        user_name=request.user_name,
    )
    try:
        result = AIAssistantService.rebuild_from_json(
            json_path=request.json_path,
            file_path=request.file_path,
            task=task,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return JSONResponse(content=jsonable_encoder(result))


if __name__ == "__main__":
    import uvicorn
    print("[INFO] Инициализация FastAPI приложения...")
    print(f"[INFO] Settings загружены: NORMATIVE_BASE={settings.normative_base}")
    print(f"[INFO] FastAPI app создан: {app}")
    print("[INFO] Запуск Uvicorn...")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        workers=1,
        log_level="info",
    )
