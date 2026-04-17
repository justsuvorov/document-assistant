from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Values are read from .env or environment variables."""

    # --- PATHS ---
    normative_base: str = Field(..., alias="NORMATIVE_BASE")
    examples_path: str = Field("", alias="EXAMPLES_PATH")

    # --- DATABASE ---
    database_url: str = Field(..., alias="DATABASE_URL")

    # --- AI ---
    gemini_api_key: SecretStr = Field(..., alias="GEMINI_API_KEY")
    model_name: str = Field("gemini-1.5-flash", alias="AI_MODEL_NAME")
    ai_temperature: float = Field(0.2, alias="AI_TEMPERATURE")

    # --- TELEGRAM (optional) ---
    telegram_bot_token: SecretStr | None = Field(None, alias="TELEGRAM_BOT_TOKEN")

    # --- PROMPT ---
    ai_role: str = Field(..., alias="AI_ROLE")
    ai_prompt_template: str = Field(..., alias="AI_PROMPT_TEMPLATE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ai_prompt_template", mode="before")
    @classmethod
    def unescape_newlines(cls, v: str) -> str:
        """Convert literal \\n sequences from .env into real newlines."""
        return v.replace("\\n", "\n")


settings = Settings()
