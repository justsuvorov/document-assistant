"""FastAPI-зависимости аутентификации.

``get_current_user`` — для /api/*: невалидный токен даёт 401.
``require_user_page`` — для HTML-страниц: невалидный токен даёт редирект на
   /auth/login, иначе неавторизованный пользователь увидел бы голый JSON.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from document_assistant.auth.keycloak import TokenClaims
from document_assistant.core.settings import settings

AUTH_COOKIE = "auth"
# Старые cookie (до 0.9 там лежали сами токены Keycloak) — удаляем при входе/выходе.
_LEGACY_COOKIES = ("access_token", "id_token")

logger = logging.getLogger(__name__)


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

    # Причину отказа кладём в request.state — её пишет в лог обработчик
    # RedirectToLogin. Без неё «бесконечный редирект на логин» не разобрать.
    raw = request.cookies.get(_cookie_name(AUTH_COOKIE))
    if not raw:
        request.state.auth_reason = f"нет cookie {_cookie_name(AUTH_COOKIE)}"
        return None
    try:
        data = _serializer().loads(raw, max_age=settings.session_max_age_hours * 3600)
    except SignatureExpired:
        request.state.auth_reason = f"сессия старше {settings.session_max_age_hours} ч"
        return None
    except BadSignature:
        # Подделка или сменился SESSION_SECRET (у подов разные значения?).
        request.state.auth_reason = "неверная подпись cookie (SESSION_SECRET одинаков во всех подах?)"
        logger.warning(f"{request.url.path}: {request.state.auth_reason}")
        return None
    if data.get("acl") != _access_policy_tag():
        # Cookie выдана до смены KEYCLOAK_ALLOWED_* — пусть пройдёт проверку заново.
        request.state.auth_reason = "изменились правила доступа, нужен повторный вход"
        return None
    return CurrentUser(
        user_id=data["sub"],
        user_name=data.get("name"),
        roles=tuple(data.get("roles", ())),
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


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret.get_secret_value(), salt="da-auth")


def _access_policy_tag() -> str:
    """Отпечаток KEYCLOAK_ALLOWED_GROUPS/ROLES: при их смене все входы сбрасываются."""
    policy = f"{settings.keycloak_allowed_groups}|{settings.keycloak_allowed_roles}"
    return hashlib.sha256(policy.encode()).hexdigest()[:12]


def set_auth_cookie(response: RedirectResponse, claims: TokenClaims) -> None:
    """Положить в cookie проверенного пользователя, а не токены Keycloak.

    Токены Keycloak с ролями и группами весят несколько КБ: браузер молча не
    сохраняет cookie больше 4 КБ (бесконечный редирект на логин), а nginx не
    пропускает такие заголовки ответа (502). Токен проверяется один раз на
    /auth/callback, дальше хватает подписанной SESSION_SECRET записи на ~200 Б.
    """
    value = _serializer().dumps({
        "sub": claims.sub,
        "name": claims.preferred_username or claims.email,
        "acl": _access_policy_tag(),
    })
    response.set_cookie(
        _cookie_name(AUTH_COOKIE), value,
        max_age=settings.session_max_age_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    for legacy in _LEGACY_COOKIES:
        response.delete_cookie(_cookie_name(legacy), path="/")
    logger.info(f"cookie авторизации: {len(value)} Б, срок {settings.session_max_age_hours} ч, "
                f"secure={settings.session_cookie_secure}")


def clear_auth_cookies(response: RedirectResponse) -> None:
    for name in (AUTH_COOKIE, *_LEGACY_COOKIES):
        response.delete_cookie(_cookie_name(name), path="/")
