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


class ReconcileRequest(BaseModel):
    """Сверка деклараций с генеральным полисом и дополнительными соглашениями (ДС)."""
    request_id: int = Field(..., description="Уникальный ID запроса")
    user_name: Optional[str] = Field(None, description="Имя пользователя (опционально)")
    policy_folder: str = Field(..., description="Путь к папке с генеральным полисом и ДС")
    declaration_paths: list[str] = Field(..., description="Пути к файлам деклараций для сверки")
    special_conditions_path: Optional[str] = Field(
        None, description="Путь к файлу особых условий клиента (опционально)"
    )
    force_rebuild_matrix: bool = Field(
        False, description="Игнорировать кэш матрицы актуальных правил и пересчитать заново"
    )
    max_chunks: int = Field(0, description="Максимальное число чанков на декларацию (0 = без ограничений)")
