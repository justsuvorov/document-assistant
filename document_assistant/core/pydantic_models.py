"""Схемы старого JSON-API (file_path/json_path на локальном диске).

Больше нигде не используются: веб-версия принимает файлы через
multipart/form-data, а пути к файлам заменены ключами S3 в таблице sessions.
Оставлены на случай, если понадобится совместимость со старыми клиентами;
если такой задачи нет — файл можно удалить.
"""

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
    max_chunks: int = Field(0, description="Максимальное число чанков (0 = из настроек)")


class EstimateRequest(BaseModel):
    """Запрос оценки времени обработки файла."""
    file_path: str = Field(..., description="Путь к файлу клиента в контейнере")
