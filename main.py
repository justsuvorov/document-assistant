from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import ModelFactory
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask, DocumentChunker
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser
from document_assistant.core.pydantic_models import APIRequest, EstimateRequest, RebuildRequest
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService

app = FastAPI()

_NUM_CTX = {
    "ollama": lambda: settings.llm_num_ctx,
    "gemini": lambda: settings.gemini_num_ctx,
    "anthropic": lambda: settings.anthropic_num_ctx,
    "qwen": lambda: settings.qwen_num_ctx,
}


def _num_ctx() -> int:
    return _NUM_CTX.get(settings.ai_provider, lambda: settings.llm_num_ctx)()


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
                num_ctx=_num_ctx(),
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
