"""FastAPI-зависимости аутентификации.

``get_current_user`` — для /api/*: невалидный токен даёт 401.
``require_user_page`` — для HTML-страниц: невалидный токен даёт редирект на
   /auth/login, иначе неавторизованный пользователь увидел бы голый JSON.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from document_assistant.auth.keycloak import decode_token
from document_assistant.core.settings import settings

ACCESS_COOKIE = "access_token"
ID_TOKEN_COOKIE = "id_token"


@dataclass(frozen=True)
class CurrentUser:
    """user_id — это claim ``sub`` из Keycloak: стабилен при смене логина."""

    user_id: str
    user_name: str | None = None
    roles: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return role in self.roles


class RedirectToLogin(Exception):
    """Страница требует логина. Обрабатывается exception handler'ом в main."""


def _dev_user() -> CurrentUser:
    return CurrentUser(user_id=settings.auth_dev_user_id, user_name="Локальный пользователь")


def _cookie_name(suffix: str) -> str:
    return f"{settings.session_cookie_name}_{suffix}"


async def _user_from_request(request: Request) -> CurrentUser | None:
    if settings.auth_disabled:
        return _dev_user()

    token = request.cookies.get(_cookie_name(ACCESS_COOKIE))
    if not token:
        return None
    try:
        claims = await decode_token(token)
    except ValueError:
        return None
    return CurrentUser(
        user_id=claims.sub,
        user_name=claims.preferred_username or claims.email,
        roles=tuple(claims.roles),
    )


async def get_current_user(request: Request) -> CurrentUser:
    """Зависимость для API. 401 при отсутствии/невалидности токена."""
    user = await _user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    return user


async def require_user_page(request: Request) -> CurrentUser:
    """Зависимость для HTML-страниц. Редирект на логин вместо 401."""
    user = await _user_from_request(request)
    if user is None:
        raise RedirectToLogin()
    return user


async def get_optional_user(request: Request) -> CurrentUser | None:
    return await _user_from_request(request)


def set_auth_cookies(response: RedirectResponse, access_token: str, id_token: str | None) -> None:
    common = {
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(_cookie_name(ACCESS_COOKIE), access_token, **common)
    if id_token:
        response.set_cookie(_cookie_name(ID_TOKEN_COOKIE), id_token, **common)


def clear_auth_cookies(response: RedirectResponse) -> None:
    response.delete_cookie(_cookie_name(ACCESS_COOKIE), path="/")
    response.delete_cookie(_cookie_name(ID_TOKEN_COOKIE), path="/")


def read_id_token(request: Request) -> str | None:
    return request.cookies.get(_cookie_name(ID_TOKEN_COOKIE))
