from pydantic import BaseModel, Field
from typing import Optional


class RebuildRequest(BaseModel):
    """Сборка результата из кэшированного JSON без вызова LLM."""
    request_id: int = Field(..., description="Уникальный ID запроса")
    json_path: str = Field(..., description="Путь к *_llm_output.json")
    file_path: str = Field(..., description="Путь к исходному файлу клиента")
    user_name: Optional[str] = Field(None, description="Имя пользователя (опционально)")


class APIRequest(BaseModel):
    """
    Схема входящего запроса для обработки файла.
    """
    request_id: int = Field(..., description="Уникальный ID запроса. ID записи в базе данных")
    user_name: Optional[str] = Field(None, description="Имя пользователя (опционально)")
    file_path: str = Field(..., description="Путь к файлу")
    priority: int = Field(0, description="Приоритет обработки")
