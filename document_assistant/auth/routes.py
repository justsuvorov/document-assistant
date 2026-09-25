"""Роуты /auth/login, /auth/callback, /auth/logout."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from document_assistant.auth.dependencies import (
    clear_auth_cookies,
    read_id_token,
    set_auth_cookies,
)
from document_assistant.auth.keycloak import keycloak_configured, logout_url, oidc_client
from document_assistant.core.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """Начать Authorization Code flow.

    При AUTH_DISABLED Keycloak не задействован — просто отправляем на главную,
    где пользователь уже считается залогиненным dev-пользователем.
    """
    if settings.auth_disabled:
        print("[INFO] /auth/login: AUTH_DISABLED=true — редирект на главную без Keycloak", flush=True)
        return RedirectResponse(url="/", status_code=302)
    if not keycloak_configured():
        print("[ERROR] /auth/login: Keycloak не сконфигурирован (KEYCLOAK_* не заданы)", flush=True)
        raise HTTPException(
            status_code=503,
            detail="Keycloak не сконфигурирован. Задайте KEYCLOAK_* в .env "
                   "или включите AUTH_DISABLED=true для локальной разработки.",
        )
    redirect_uri = str(request.url_for("auth_callback"))
    print(f"[INFO] /auth/login: редирект на Keycloak, callback={redirect_uri}", flush=True)
    return await oidc_client().authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Обменять code на токены и положить их в httponly-cookie."""
    if settings.auth_disabled:
        return RedirectResponse(url="/", status_code=302)
    try:
        token = await oidc_client().authorize_access_token(request)
    except Exception as e:
        print(f"[ERROR] /auth/callback: обмен code на токен не удался — {e}", flush=True)
        raise HTTPException(status_code=401, detail=f"Не удалось получить токен: {e}")

    access_token = token.get("access_token")
    if not access_token:
        print("[ERROR] /auth/callback: Keycloak не вернул access_token", flush=True)
        raise HTTPException(status_code=401, detail="Keycloak не вернул access_token")

    print("[INFO] /auth/callback: токен получен, cookie выставлена", flush=True)
    response = RedirectResponse(url="/", status_code=302)
    set_auth_cookies(response, access_token, token.get("id_token"))
    return response


@router.get("/logout")
async def logout(request: Request):
    """Погасить нашу cookie и, если возможно, SSO-сессию в Keycloak."""
    id_token = read_id_token(request)
    if settings.auth_disabled or not keycloak_configured():
        response = RedirectResponse(url="/", status_code=302)
    else:
        home = str(request.url_for("index_page"))
        response = RedirectResponse(url=logout_url(home, id_token), status_code=302)
    print("[INFO] /auth/logout: cookie очищена", flush=True)
    clear_auth_cookies(response)
    return response
