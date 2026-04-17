from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    """
    Класс настроек приложения.
    Автоматически считывает переменные из .env или окружения.
    """
    normative_base: str = Field(..., aliase='NORMATIVE_BASE')
    database_url: str = Field(..., alias="DATABASE_URL")

    # --- AI SETTINGS ---
    gemini_api_key: SecretStr = Field(..., alias="GEMINI_API_KEY")
    model_name: str = Field("gemini-1.5-flash", alias="AI_MODEL_NAME")
    ai_temperature: float = Field(0.8, alias="AI_TEMPERATURE")

    # --- TELEGRAM ---
    telegram_bot_token: SecretStr | None = Field(None, alias="TELEGRAM_BOT_TOKEN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Игнорировать лишние переменные в .env
    )
    # --- PROMPT SETTINGS (Выносим всё сюда) ---

    # Системная роль: кто такой наш ИИ?
    ai_role: str = (
        "Ты — профессиональный технический редактор. Твоя задача: "
        "перерабатывать сырые мысли в структурированные посты."
    )

    # Шаблон промпта: каркас, куда вставляются данные
    # Ключи в фигурных скобках {key} должны совпадать с аргументами .format()
    ai_prompt_template: str = """
    {role}

    ### ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ:
    {extra}

    ### ПРИМЕРЫ СТИЛЯ (ЭТАЛОНЫ):
    {examples}

    ### ИСХОДНЫЙ ТЕКСТ (ТРАНСКРИПЦИЯ):
    "{source_text}"

    ### ИТОГОВЫЙ РЕЗУЛЬТАТ:
    """


# Создаем экземпляр настроек (Singleton)
settings = Settings()
