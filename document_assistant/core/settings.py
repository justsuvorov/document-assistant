import sys
from pathlib import Path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path:
    """Find .env file in multiple locations for both dev and EXE environments."""
    candidates = [
        Path.cwd() / ".env",  # Current working directory
        Path(__file__).parent.parent.parent / ".env",  # Project root (dev)
        Path(__file__).parent.parent.parent / "dist" / ".env",  # dist/ folder (dev)
    ]

    # For PyInstaller EXE, also check where the EXE is located
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        candidates.insert(0, exe_dir / ".env")  # Check EXE directory first

    for path in candidates:
        if path.exists():
            return path

    return Path.cwd() / ".env"  # Fallback


_ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    """Application settings. Values are read from .env or environment variables."""

    # --- PATHS ---
    normative_base: str = Field(..., alias="NORMATIVE_BASE")
    examples_path: str = Field("", alias="EXAMPLES_PATH")

    # --- Cargo reconciliation (сверка деклараций с ген. полисом) ---
    reconciliation_rules_base: str = Field("", alias="RECONCILIATION_RULES_BASE")
    special_conditions_global_path: str = Field("", alias="SPECIAL_CONDITIONS_GLOBAL_PATH")
    reconciliation_output_template_path: str = Field("", alias="RECONCILIATION_OUTPUT_TEMPLATE_PATH")

    @field_validator(
        "normative_base",
        "examples_path",
        "reconciliation_rules_base",
        "special_conditions_global_path",
        "reconciliation_output_template_path",
        mode="after",
    )
    @classmethod
    def resolve_relative_paths(cls, v: str) -> str:
        """Convert relative paths to absolute, relative to project/dist directory."""
        if not v:
            return v
        p = Path(v)
        if p.is_absolute():
            return str(p)
        # Try to resolve relative to current directory first
        if (Path.cwd() / v).exists():
            return str((Path.cwd() / v).resolve())
        # Then try dist/ directory
        if (Path(__file__).parent.parent.parent / "dist" / v).exists():
            return str((Path(__file__).parent.parent.parent / "dist" / v).resolve())
        # Then project root
        if (Path(__file__).parent.parent.parent / v).exists():
            return str((Path(__file__).parent.parent.parent / v).resolve())
        # Return as-is if nothing found
        return str(p.resolve())

    # --- AI (общее) ---
    # Допустимые значения: "ollama" | "gemini" | "anthropic"
    ai_provider: str = Field("ollama", alias="AI_PROVIDER")
    ai_temperature: float = Field(0.2, alias="AI_TEMPERATURE")

    # --- Ollama (локальный Docker или удалённый GPU-сервер) ---
    llm_base_url: str = Field("http://ollama:11434", alias="LLM_BASE_URL")
    llm_model_name: str = Field("qwen2.5:7b", alias="LLM_MODEL_NAME")
    llm_max_chars: int = Field(60_000, alias="LLM_MAX_CHARS")
    llm_num_ctx: int = Field(32_768, alias="LLM_NUM_CTX")
    llm_max_sections: int = Field(300, alias="LLM_MAX_SECTIONS")
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

    # --- Qwen (OpenAI-compatible API, /v1/completions) ---
    qwen_api_url: str = Field("", alias="QWEN_API_URL")
    qwen_model_name: str = Field("qwen-plus", alias="QWEN_MODEL_NAME")
    qwen_max_tokens: int = Field(100_000, alias="QWEN_MAX_TOKENS")
    qwen_num_ctx: int = Field(400_000, alias="QWEN_NUM_CTX")  # полное контекстное окно модели

    # --- VSK AI (OpenAI-compatible chat API, /v1/chat/completions) ---
    vsk_api_url: str = Field("https://llm.ai-api.vsk.ru/v1/chat/completions", alias="VSK_API_URL")
    vsk_api_key: SecretStr | None = Field("", alias="VSK_API_KEY")
    vsk_model_name: str = Field("Qwen3.6-35B-A3B", alias="VSK_MODEL_NAME")
    vsk_max_tokens: int = Field(100_000, alias="VSK_MAX_TOKENS")
    vsk_thinking_token_budget: int = Field(1_000, alias="VSK_THINKING_TOKEN_BUDGET")
    vsk_num_ctx: int = Field(400_000, alias="VSK_NUM_CTX")  # полное контекстное окно модели

    # --- PROMPT ---
    ai_role: str = Field(..., alias="AI_ROLE")
    ai_prompt_template: str = Field(..., alias="AI_PROMPT_TEMPLATE")

    # --- PROMPT: cargo reconciliation ---
    matrix_ai_role: str = Field("", alias="MATRIX_AI_ROLE")
    matrix_prompt_template: str = Field("", alias="MATRIX_PROMPT_TEMPLATE")
    reconciliation_ai_role: str = Field("", alias="RECONCILIATION_AI_ROLE")
    reconciliation_prompt_template: str = Field("", alias="RECONCILIATION_PROMPT_TEMPLATE")

    # Формат strftime для названия месячной папки в "Декларации/{месяц}/" (используется
    # только для предупреждения о несоответствии папки, файлы физически не переносятся)
    declarations_month_format: str = Field("%Y-%m", alias="DECLARATIONS_MONTH_FORMAT")

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ai_prompt_template", "matrix_prompt_template", "reconciliation_prompt_template", mode="before")
    @classmethod
    def unescape_newlines(cls, v: str) -> str:
        """Convert literal \\n sequences from .env into real newlines."""
        return v.replace("\\n", "\n") if v else v


settings = Settings()
