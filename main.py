import traceback

from fastapi import FastAPI, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from document_assistant.ai.encoders import TextEncoder
from document_assistant.ai.model import GeminiModel
from document_assistant.ai.postprocessor import PostProcessor
from document_assistant.ai.preprocessor import DocumentPreprocessor, ProcessingTask
from document_assistant.ai.promt_builders import PromptEngine
from document_assistant.core.parsers import DataParser
from document_assistant.core.pydantic_models import APIRequest
from document_assistant.core.settings import settings
from document_assistant.reports.report_export import ReportExport
from document_assistant.services.assistant import AIAssistantService

app = FastAPI()


@app.post("/api/update")
def main(request: APIRequest):
    processing_task = ProcessingTask(
        request_id=request.request_id,
        file_path=request.file_path,
        user_name=request.user_name,
    )

    print(f"Запрос получен: {request.file_path}", flush=True)
    print("Запуск обработки", flush=True)

    ai = AIAssistantService(
        preprocessor=DocumentPreprocessor(
            data_parser=DataParser(file_path=request.file_path),
            request=processing_task,
            encoder=TextEncoder(),
            prompt_engine=PromptEngine(
                role=settings.ai_role,
                template=settings.ai_prompt_template,
                normative_base=settings.normative_base,
            ),
            examples_path=settings.examples_path,
        ),
        postprocessor=PostProcessor(),
        ai_model=GeminiModel(),
        report_export=ReportExport(processing_task),
    )

    try:
        response = ai.result()
        return JSONResponse(
            content=jsonable_encoder(response),
            status_code=status.HTTP_200_OK,
        )
    except Exception:
        response = {"error": traceback.format_exc()}
        return JSONResponse(
            content=jsonable_encoder(response),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
