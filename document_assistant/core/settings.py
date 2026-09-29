import logging
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict



logger = logging.getLogger(__name__)

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

    # --- VSK AI (OpenAI-compatible CHAT API, /v1/chat/completions) ---
    # Включается через AI_PROVIDER=vsk. В отличие от Qwen здесь chat-формат
    # (messages[]), а не completions (prompt), и нужен Bearer-токен.
    vsk_api_url: str = Field("", alias="VSK_API_URL")
    vsk_api_key: SecretStr | None = Field(None, alias="VSK_API_KEY")
    vsk_model_name: str = Field("", alias="VSK_MODEL_NAME")
    vsk_max_tokens: int = Field(100_000, alias="VSK_MAX_TOKENS")
    vsk_thinking_token_budget: int = Field(1_000, alias="VSK_THINKING_TOKEN_BUDGET")
    vsk_num_ctx: int = Field(400_000, alias="VSK_NUM_CTX")  # полное контекстное окно модели

    # --- PROMPT ---
    ai_role: str = Field(..., alias="AI_ROLE")
    ai_prompt_template: str = Field(..., alias="AI_PROMPT_TEMPLATE")

    # --- Логирование ---
    # DEBUG/INFO/WARNING/ERROR. Поднимается через ConfigMap без пересборки образа.
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # --- Хранилище файлов (локальный диск сервера) ---
    # Каталог, куда складываются входные файлы и результаты. Внутри —
    # структура {user_id}/{session_id}/input|output/. Должен быть доступен на
    # запись и api, и воркеру: в compose это общий том.
    storage_dir: str = Field("./data", alias="STORAGE_DIR")

    # --- База метаданных сессий ---
    database_url: str = Field("sqlite+aiosqlite:///./document_assistant.db", alias="DATABASE_URL")

    # --- Очередь задач (таблица sessions в БД) ---
    # Каждая задача занимает поток целиком (доменная логика синхронная),
    # поэтому параллелизм по умолчанию скромный.
    worker_max_jobs: int = Field(2, alias="WORKER_MAX_JOBS")
    worker_job_timeout: int = Field(7200, alias="WORKER_JOB_TIMEOUT")
    # Как часто воркер заглядывает в БД за новой задачей, секунды.
    worker_poll_interval: float = Field(2.0, alias="WORKER_POLL_INTERVAL")
    # Задача, висящая в processing дольше этого, считается брошенной (воркер
    # убит) и возвращается в очередь. Должно быть заметно больше самой долгой
    # обработки, иначе живую задачу подхватит второй воркер.
    worker_stale_timeout: int = Field(10800, alias="WORKER_STALE_TIMEOUT")
    # Сколько раз пробовать задачу, прежде чем признать её ошибкой.
    worker_max_attempts: int = Field(3, alias="WORKER_MAX_ATTEMPTS")

    # --- Keycloak / OIDC ---
    # AUTH_DISABLED=true — локальная разработка без Keycloak: get_current_user()
    # возвращает AUTH_DEV_USER_ID. В проде обязано быть false.
    auth_disabled: bool = Field(False, alias="AUTH_DISABLED")
    auth_dev_user_id: str = Field("dev-user", alias="AUTH_DEV_USER_ID")
    keycloak_url: str = Field("", alias="KEYCLOAK_URL")
    keycloak_realm: str = Field("", alias="KEYCLOAK_REALM")
    keycloak_client_id: str = Field("", alias="KEYCLOAK_CLIENT_ID")
    keycloak_client_secret: SecretStr = Field(SecretStr(""), alias="KEYCLOAK_CLIENT_SECRET")
    # false — не проверять TLS-сертификат Keycloak (самоподписанный/внутренний CA).
    keycloak_verify_ssl: bool = Field(False, alias="KEYCLOAK_VERIFY_SSL")
    # Кого пускать: через запятую. Пользователь проходит, если состоит ХОТЯ БЫ
    # в одной группе ИЛИ имеет хотя бы одну роль (realm или клиента). Оба пустые —
    # пускаем всех пользователей realm (на старте пишется WARNING).
    # Группы попадают в токен только при mapper «Group Membership» (claim groups).
    keycloak_allowed_groups: str = Field("", alias="KEYCLOAK_ALLOWED_GROUPS")
    keycloak_allowed_roles: str = Field("", alias="KEYCLOAK_ALLOWED_ROLES")
    # Секрет подписи cookie-сессии. В проде задать явно.
    session_secret: SecretStr = Field(SecretStr("dev-insecure-session-secret"), alias="SESSION_SECRET")
    session_cookie_name: str = Field("da_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(False, alias="SESSION_COOKIE_SECURE")
    # Сколько живёт вход в приложение, после — снова через Keycloak (обычно без ввода пароля, по SSO).
    session_max_age_hours: int = Field(8, alias="SESSION_MAX_AGE_HOURS")

    @property
    def keycloak_oidc_base(self) -> str:
        """{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect — база эндпоинтов
        Keycloak. Discovery (.well-known) не используем: в контуре он отдаёт 404.
        Пустая строка, если Keycloak не сконфигурирован."""
        if not self.keycloak_url or not self.keycloak_realm:
            return ""
        return (
            f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect"
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


def active_model_endpoint() -> str:

    if settings.ai_provider == "vsk":
        return settings.vsk_api_url or "<НЕ ЗАДАН VSK_API_URL>"
    return settings.qwen_api_url or "<НЕ ЗАДАН QWEN_API_URL>"


def warn_if_state_not_shared() -> None:

    url = settings.database_url
    if url.startswith("sqlite") and ":///./" in url:
        logger.warning(
            f"DATABASE_URL={url} — SQLite с относительным путём. "
            "Если api и worker запущены как разные контейнеры/процессы с разным "
            "рабочим каталогом, у каждого будет СВОЯ база: задачи не будут "
            "подхватываться воркером. Для нескольких процессов нужен общий "
            "Postgres (DATABASE_URL=postgresql+asyncpg://...).")

    if not Path(settings.storage_dir).is_absolute():
        logger.warning(
            f"STORAGE_DIR={settings.storage_dir} — относительный путь. "
            "api и worker должны видеть ОДИН каталог (общий том); при "
            "относительном пути каждый процесс получит свой собственный, "
            "и воркер не найдёт загруженные файлы.")
