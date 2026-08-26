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

    # --- Qwen (OpenAI-compatible API) ---
    qwen_api_url: str = Field("", alias="QWEN_API_URL")
    qwen_model_name: str = Field("qwen-plus", alias="QWEN_MODEL_NAME")
    qwen_max_tokens: int = Field(100_000, alias="QWEN_MAX_TOKENS")
    qwen_num_ctx: int = Field(400_000, alias="QWEN_NUM_CTX")  # полное контекстное окно модели

    # --- PROMPT ---
    ai_role: str = Field(..., alias="AI_ROLE")
    ai_prompt_template: str = Field(..., alias="AI_PROMPT_TEMPLATE")

    # --- S3 / MinIO ---
    # Пустой endpoint_url = AWS S3. Для MinIO/Ceph указывать явно.
    s3_endpoint_url: str = Field("", alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field("document-assistant", alias="S3_BUCKET")
    s3_access_key: str = Field("", alias="S3_ACCESS_KEY")
    s3_secret_key: SecretStr = Field(SecretStr(""), alias="S3_SECRET_KEY")
    s3_region: str = Field("us-east-1", alias="S3_REGION")
    # MinIO и Ceph требуют path-style адресацию; AWS работает и так, и так.
    s3_use_path_style: bool = Field(True, alias="S3_USE_PATH_STYLE")
    s3_presign_expires: int = Field(3600, alias="S3_PRESIGN_EXPIRES")

    # --- База метаданных сессий ---
    database_url: str = Field("sqlite+aiosqlite:///./document_assistant.db", alias="DATABASE_URL")

    # --- Очередь задач (arq + Redis) ---
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    # Каждая задача занимает поток целиком (доменная логика синхронная),
    # поэтому параллелизм по умолчанию скромный.
    worker_max_jobs: int = Field(2, alias="WORKER_MAX_JOBS")
    worker_job_timeout: int = Field(7200, alias="WORKER_JOB_TIMEOUT")

    # --- Keycloak / OIDC ---
    # AUTH_DISABLED=true — локальная разработка без Keycloak: get_current_user()
    # возвращает AUTH_DEV_USER_ID. В проде обязано быть false.
    auth_disabled: bool = Field(False, alias="AUTH_DISABLED")
    auth_dev_user_id: str = Field("dev-user", alias="AUTH_DEV_USER_ID")
    keycloak_url: str = Field("", alias="KEYCLOAK_URL")
    keycloak_realm: str = Field("", alias="KEYCLOAK_REALM")
    keycloak_client_id: str = Field("", alias="KEYCLOAK_CLIENT_ID")
    keycloak_client_secret: SecretStr = Field(SecretStr(""), alias="KEYCLOAK_CLIENT_SECRET")
    # Секрет подписи cookie-сессии. В проде задать явно.
    session_secret: SecretStr = Field(SecretStr("dev-insecure-session-secret"), alias="SESSION_SECRET")
    session_cookie_name: str = Field("da_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(False, alias="SESSION_COOKIE_SECURE")

    @property
    def keycloak_metadata_url(self) -> str:
        """OIDC discovery endpoint. Пустая строка, если Keycloak не сконфигурирован."""
        if not self.keycloak_url or not self.keycloak_realm:
            return ""
        return (
            f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"
            "/.well-known/openid-configuration"
        )

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
