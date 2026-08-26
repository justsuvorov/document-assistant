"""Точка входа веб-приложения.

Длинная LLM-обработка ушла в arq-воркер (``document_assistant.worker.tasks``),
здесь остаются только быстрые операции: приём файлов, статусы, страницы.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from document_assistant.auth.dependencies import RedirectToLogin
from document_assistant.auth.keycloak import register_oauth_client
from document_assistant.auth.routes import router as auth_router
from document_assistant.core.settings import settings
from document_assistant.db.engine import dispose_engine, init_db
from document_assistant.storage import storage
from document_assistant.web.api import router as api_router
from document_assistant.web.pages import router as pages_router
from document_assistant.worker.queue import close_arq_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    register_oauth_client()
    try:
        storage.ensure_bucket()
    except Exception as e:
        # Приложение поднимаем в любом случае: без S3 сломается загрузка
        # файлов, но страница логина и история сессий останутся доступны,
        # и в логах будет видна настоящая причина.
        print(f"[WARN] S3 недоступен на старте: {e}", flush=True)
    if settings.auth_disabled:
        print("[WARN] AUTH_DISABLED=true — авторизация отключена, "
              "все запросы идут от пользователя "
              f"'{settings.auth_dev_user_id}'. Не используйте в проде.", flush=True)
    yield
    await close_arq_pool()
    await dispose_engine()


app = FastAPI(title="ДМС-ассистент", lifespan=lifespan)

# Нужна authlib для хранения state/nonce между /auth/login и /auth/callback.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret.get_secret_value(),
    https_only=settings.session_cookie_secure,
    same_site="lax",
)

app.include_router(auth_router)
app.include_router(api_router)
app.include_router(pages_router)


@app.exception_handler(RedirectToLogin)
async def redirect_to_login(request: Request, exc: RedirectToLogin):
    """Неавторизованный пользователь на HTML-странице уходит на логин."""
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
