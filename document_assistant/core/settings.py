from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Values are read from .env or environment variables."""

    # --- PATHS ---
    normative_base: str = Field(..., alias="NORMATIVE_BASE")
    examples_path: str = Field("", alias="EXAMPLES_PATH")

    # --- AI (общее) ---
    # Допустимые значения: "ollama" | "gemini" | "anthropic"
    ai_provider: str = Field("ollama", alias="AI_PROVIDER")
    ai_temperature: float = Field(0.2, alias="AI_TEMPERATURE")

    # --- Ollama (локальный Docker или удалённый GPU-сервер) ---
    llm_base_url: str = Field("http://ollama:11434", alias="LLM_BASE_URL")
    llm_model_name: str = Field("qwen2.5:7b", alias="LLM_MODEL_NAME")
    llm_max_chars: int = Field(60_000, alias="LLM_MAX_CHARS")
    llm_num_ctx: int = Field(32_768, alias="LLM_NUM_CTX")
    llm_max_sections: int = Field(15, alias="LLM_MAX_SECTIONS")
    llm_max_chunks: int = Field(0, alias="LLM_MAX_CHUNKS")  # 0 = без ограничений
    llm_batch_size: int = Field(25, alias="LLM_BATCH_SIZE")

    # --- Gemini ---
    gemini_api_key: SecretStr | None = Field(None, alias="GEMINI_API_KEY")
    model_name: str = Field("gemini-2.0-flash", alias="AI_MODEL_NAME")
    gemini_num_ctx: int = Field(1_000_000, alias="GEMINI_NUM_CTX")

    # --- Anthropic ---
    anthropic_api_key: SecretStr | None = Field(None, alias="ANTHROPIC_API_KEY")
    anthropic_model_name: str = Field("claude-sonnet-4-6", alias="ANTHROPIC_MODEL_NAME")
    anthropic_num_ctx: int = Field(200_000, alias="ANTHROPIC_NUM_CTX")

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
