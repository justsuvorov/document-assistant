from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import ModelFactory
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser
from document_assistant.core.pydantic_models import APIRequest
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService

app = FastAPI()

_NUM_CTX = {
    "ollama": lambda: settings.llm_num_ctx,
    "gemini": lambda: settings.gemini_num_ctx,
    "anthropic": lambda: settings.anthropic_num_ctx,
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


@app.post("/api/update")
def submit(request: APIRequest):
    ai = _build_service(request)
    result = ai.result()
    return JSONResponse(content=jsonable_encoder(result))
