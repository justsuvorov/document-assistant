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
    """Сверка деклараций с генеральным полисом и дополнительными соглашениями (ДС).

    По умолчанию генеральный полис ищется в policy_folder как файл "ГП ...",
    а ДС — в подпапке policy_folder/ДС/ (файлы вида "ДС 3 (п.9, п. 7)").
    Оба пути можно переопределить явно через policy_file_override/ds_folder_override.

    declaration_paths может отсутствовать — тогда декларации берутся из
    подпапки policy_folder/Декларации/ (рекурсивно, включая помесячные
    подпапки). Каждый элемент declaration_paths может быть как путём к
    файлу, так и путём к папке (папка сканируется рекурсивно).
    """
    request_id: int = Field(..., description="Уникальный ID запроса")
    user_name: Optional[str] = Field(None, description="Имя пользователя (опционально)")
    policy_folder: str = Field(..., description="Путь к папке с генеральным полисом и ДС")
    policy_file_override: Optional[str] = Field(
        None, description="Явный путь к файлу ген.полиса (переопределяет автопоиск файла 'ГП ...')"
    )
    ds_folder_override: Optional[str] = Field(
        None, description="Явный путь к папке с ДС (переопределяет папку 'ДС' по умолчанию)"
    )
    declaration_paths: Optional[list[str]] = Field(
        None,
        description="Пути к файлам и/или папкам деклараций. Пусто = папка 'Декларации' в policy_folder",
    )
    special_conditions_path: Optional[str] = Field(
        None, description="Путь к файлу особых условий клиента (опционально)"
    )
    force_rebuild_matrix: bool = Field(
        True, description="Игнорировать кэш матрицы актуальных правил и пересчитать заново (по умолчанию — да)"
    )
    max_chunks: int = Field(0, description="Максимальное число чанков на декларацию (0 = без ограничений)")
