"""Роуты /auth/login, /auth/callback, /auth/logout."""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from document_assistant.auth.dependencies import (
    clear_auth_cookies,
    set_auth_cookie,
)
from document_assistant.auth.keycloak import (
    access_denied_reason,
    decode_token,
    keycloak_configured,
    logout_url,
    oidc_client,
)
from document_assistant.core.settings import settings


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_ACCESS_DENIED_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Нет доступа</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:80px auto;padding:0 16px">
<h1>Нет доступа</h1>
<p>Пользователь <b>{login}</b> вошёл в систему, но не состоит в группе,
которой разрешён доступ к ДМС-ассистенту.</p>
<p>Обратитесь к администратору, чтобы вас добавили в группу.</p>
<p><a href="/auth/logout">Войти под другим пользователем</a></p>
</body></html>"""


@router.get("/login")
async def login(request: Request):
    """Начать Authorization Code flow.

    При AUTH_DISABLED Keycloak не задействован — просто отправляем на главную,
    где пользователь уже считается залогиненным dev-пользователем.
    """
    if settings.auth_disabled:
        logger.info("/auth/login: AUTH_DISABLED=true — редирект на главную без Keycloak")
        return RedirectResponse(url="/", status_code=302)
    if not keycloak_configured():
        logger.error("/auth/login: Keycloak не сконфигурирован (KEYCLOAK_* не заданы)")
        raise HTTPException(
            status_code=503,
            detail="Keycloak не сконфигурирован. Задайте KEYCLOAK_* в .env "
                   "или включите AUTH_DISABLED=true для локальной разработки.",
        )
    redirect_uri = str(request.url_for("auth_callback"))
    logger.info(f"/auth/login: редирект на Keycloak, callback={redirect_uri}")
    try:
        return await oidc_client().authorize_redirect(request, redirect_uri)
    except Exception as e:
        # Чаще всего — недоступен Keycloak или ошибка TLS.
        logger.error(f"/auth/login: не удалось начать вход через Keycloak "
                     f"{settings.keycloak_oidc_base} — {e}")
        raise HTTPException(status_code=502, detail=f"Keycloak недоступен: {e}")


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Обменять code на токены и положить их в httponly-cookie."""
    if settings.auth_disabled:
        return RedirectResponse(url="/", status_code=302)

    params = request.query_params
    if params.get("error"):
        # Keycloak сам вернул ошибку (отказ в доступе, неверный клиент и т.п.).
        logger.error(f"/auth/callback: Keycloak вернул ошибку {params.get('error')} — "
                     f"{params.get('error_description', '')}")
        raise HTTPException(status_code=401, detail=f"Keycloak: {params.get('error')} "
                                                    f"{params.get('error_description', '')}")
    # state/nonce хранятся в сессионной cookie между /auth/login и /callback.
    # Если её нет — cookie потерялась (другой домен, secure по http) и authlib
    # упадёт с mismatching_state.
    state_keys = [k for k in request.session if k.startswith("_state_")]
    logger.info(f"/auth/callback: code={'есть' if params.get('code') else 'НЕТ'}, "
                f"state={'есть' if params.get('state') else 'НЕТ'}, "
                f"сохранённых state в сессии={len(state_keys)}")

    try:
        token = await oidc_client().authorize_access_token(request)
    except Exception as e:
        logger.error(f"/auth/callback: обмен code на токен ({settings.keycloak_oidc_base}/token) "
                     f"не удался — {type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail=f"Не удалось получить токен: {e}")

    access_token = token.get("access_token")
    if not access_token:
        logger.error(f"/auth/callback: Keycloak не вернул access_token, ключи ответа: {sorted(token)}")
        raise HTTPException(status_code=401, detail="Keycloak не вернул access_token")

    try:
        claims = await decode_token(access_token)
        logger.info(f"/auth/callback: вход выполнен — sub={claims.sub}, "
                    f"login={claims.preferred_username}, ролей={len(claims.roles)}")
    except Exception as e:
        # Иначе пользователь уйдёт на главную и сразу вернётся на логин — по кругу.
        logger.error(f"/auth/callback: полученный токен не проходит проверку — "
                     f"{type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail=f"Токен Keycloak не прошёл проверку: {e}")

    denied = access_denied_reason(claims)
    if denied:
        logger.warning(f"/auth/callback: доступ ЗАПРЕЩЁН — sub={claims.sub}, "
                       f"login={claims.preferred_username}: {denied}")
        response = HTMLResponse(_ACCESS_DENIED_HTML.format(
            login=html.escape(claims.preferred_username or claims.sub)), status_code=403)
        clear_auth_cookies(response)
        return response
    logger.info(f"/auth/callback: доступ разрешён — login={claims.preferred_username}")

    response = RedirectResponse(url="/", status_code=302)
    set_auth_cookie(response, claims)
    return response


@router.get("/logout")
async def logout(request: Request):
    """Погасить нашу cookie и, если возможно, SSO-сессию в Keycloak."""
    if settings.auth_disabled or not keycloak_configured():
        response = RedirectResponse(url="/", status_code=302)
    else:
        home = str(request.url_for("index_page"))
        response = RedirectResponse(url=logout_url(home), status_code=302)
    logger.info("/auth/logout: cookie очищена")
    clear_auth_cookies(response)
    return response
