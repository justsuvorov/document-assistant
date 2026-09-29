import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

from document_assistant.auth.dependencies import RedirectToLogin
from document_assistant.auth.keycloak import register_oauth_client
from document_assistant.auth.routes import router as auth_router
from document_assistant.core.logging_config import setup_logging
from document_assistant.core.settings import (
    active_model_endpoint,
    settings,
    warn_if_state_not_shared,
)
from document_assistant.db.engine import dispose_engine, init_db, masked_database_url
from document_assistant.storage import storage
from document_assistant.web.api import router as api_router
from document_assistant.web.pages import router as pages_router
from document_assistant.web.request_log import RequestLogMiddleware

logger = logging.getLogger(__name__)


def _log_effective_config() -> None:
    logger.info(
        "Конфигурация: "
        f"БД={masked_database_url()}, "
        f"хранилище={settings.storage_dir}, "
        f"модель={settings.ai_provider or '<AI_PROVIDER не задан>'} → {active_model_endpoint()}, "
        f"нормативка={settings.normative_base}, "
        f"auth={'ОТКЛЮЧЕНА' if settings.auth_disabled else 'Keycloak ' + (settings.keycloak_url or '<не задан>')}")
    if not settings.auth_disabled:
        logger.info(
            "Keycloak: "
            f"url={settings.keycloak_url or '<не задан>'}, "
            f"realm={settings.keycloak_realm or '<не задан>'}, "
            f"client_id={settings.keycloak_client_id or '<не задан>'}, "
            f"client_secret={'задан' if settings.keycloak_client_secret.get_secret_value() else 'НЕ ЗАДАН'}, "
            f"эндпоинты={settings.keycloak_oidc_base or '<нет>'}/{{auth,token,certs,logout}}, "
            f"verify_ssl={settings.keycloak_verify_ssl}, "
            f"cookie_secure={settings.session_cookie_secure}, "
            f"session_secret={'дефолтный (НЕБЕЗОПАСНО)' if settings.session_secret.get_secret_value() == 'dev-insecure-session-secret' else 'задан'}")
        if settings.keycloak_allowed_groups or settings.keycloak_allowed_roles:
            logger.info(f"Доступ: группы={settings.keycloak_allowed_groups or '—'}, "
                        f"роли={settings.keycloak_allowed_roles or '—'}")
        else:
            logger.warning("KEYCLOAK_ALLOWED_GROUPS и KEYCLOAK_ALLOWED_ROLES не заданы — "
                           "доступ открыт ЛЮБОМУ пользователю realm")
        if not settings.keycloak_verify_ssl:
            logger.warning("KEYCLOAK_VERIFY_SSL=false — TLS-сертификат Keycloak не проверяется")
    warn_if_state_not_shared()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    _log_effective_config()
    try:
        await init_db()
    except Exception as e:
        # Без этого причина видна только в traceback'е "Application startup
        # failed", который в kubectl logs читается плохо.
        logger.error(
            f"Не удалось подключиться к БД {masked_database_url()}: "
            f"{type(e).__name__}: {e}. Проверьте доступность хоста и порта БД "
            "из кластера и DATABASE_URL в secret.")
        raise
    logger.info("Подключение к БД установлено, схема актуальна")
    register_oauth_client()
    try:
        storage.ensure_root()
    except Exception as e:
        # Приложение поднимаем в любом случае: без каталога сломается загрузка
        # файлов, но страница логина и история сессий останутся доступны,
        # и в логах будет видна настоящая причина.
        logger.warning(f"Каталог хранилища недоступен на старте: {e}")
    if settings.auth_disabled:
        logger.warning("AUTH_DISABLED=true — авторизация отключена, "
              "все запросы идут от пользователя "
              f"'{settings.auth_dev_user_id}'. Не используйте в проде.")
    yield
    await dispose_engine()


app = FastAPI(title="ДМС-ассистент", lifespan=lifespan)

# Нужна authlib для хранения state/nonce между /auth/login и /auth/callback.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    https_only=settings.session_cookie_secure,
    same_site="lax",
)

# Последним — значит, самым внешним: логирует запрос до всех остальных слоёв.
app.add_middleware(RequestLogMiddleware)

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(pages_router)


@app.exception_handler(RedirectToLogin)
async def redirect_to_login(request: Request, exc: RedirectToLogin):
    """Неавторизованный пользователь на HTML-странице уходит на логин."""
    reason = getattr(request.state, "auth_reason", "не указана")
    logger.info(f"{request.url.path}: нет авторизации ({reason}) → редирект на /auth/login")
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
