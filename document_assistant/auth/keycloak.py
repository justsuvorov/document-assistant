"""Интеграция с Keycloak по OIDC Authorization Code flow.

Токен кладётся в httponly-cookie и проверяется на каждом запросе по JWKS
реалма. Ключи кэшируются в памяти процесса и перезапрашиваются, если попался
неизвестный ``kid`` (ротация ключей в Keycloak).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from authlib.integrations.starlette_client import OAuth
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError

from document_assistant.core.settings import settings

_OIDC_NAME = "keycloak"

oauth = OAuth()


def keycloak_configured() -> bool:
    return bool(
        settings.keycloak_metadata_url
        and settings.keycloak_client_id
        and settings.keycloak_client_secret.get_secret_value()
    )


def register_oauth_client() -> None:
    """Зарегистрировать OIDC-клиента. Без конфига — тихо пропускаем.

    При AUTH_DISABLED=true приложение обязано подниматься без Keycloak, поэтому
    отсутствие конфига здесь не ошибка.
    """
    if not keycloak_configured() or _OIDC_NAME in oauth._registry:
        return
    oauth.register(
        name=_OIDC_NAME,
        server_metadata_url=settings.keycloak_metadata_url,
        client_id=settings.keycloak_client_id,
        client_secret=settings.keycloak_client_secret.get_secret_value(),
        client_kwargs={"scope": "openid profile email"},
    )


def oidc_client():
    register_oauth_client()
    return getattr(oauth, _OIDC_NAME)


@dataclass
class TokenClaims:
    sub: str
    preferred_username: str | None
    email: str | None
    roles: list[str]


class JWKSCache:
    """JWKS реалма с ленивой загрузкой и принудительным обновлением."""

    def __init__(self, ttl_seconds: int = 3600):
        self._keys: JsonWebKey | None = None
        self._fetched_at: float = 0.0
        self._ttl = ttl_seconds

    async def get(self, force_refresh: bool = False) -> JsonWebKey:
        expired = time.time() - self._fetched_at > self._ttl
        if self._keys is None or expired or force_refresh:
            self._keys = JsonWebKey.import_key_set(await self._fetch())
            self._fetched_at = time.time()
        return self._keys

    async def _fetch(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            meta = (await client.get(settings.keycloak_metadata_url)).json()
            return (await client.get(meta["jwks_uri"])).json()


_jwks = JWKSCache()


async def decode_token(token: str) -> TokenClaims:
    """Проверить подпись и срок жизни токена, вернуть нужные нам claims.

    Raises ValueError, если токен невалиден — вызывающий превращает это в 401.
    """
    try:
        claims = await _decode_with_jwks(token, force_refresh=False)
    except JoseError:
        # Возможна ротация ключей — один раз перечитываем JWKS и пробуем снова.
        try:
            claims = await _decode_with_jwks(token, force_refresh=True)
        except JoseError as e:
            raise ValueError(f"Невалидный токен: {e}") from e

    sub = claims.get("sub")
    if not sub:
        raise ValueError("В токене нет claim 'sub'")

    return TokenClaims(
        sub=sub,
        preferred_username=claims.get("preferred_username") or claims.get("name"),
        email=claims.get("email"),
        roles=list(claims.get("realm_access", {}).get("roles", [])),
    )


async def _decode_with_jwks(token: str, force_refresh: bool) -> dict:
    key_set = await _jwks.get(force_refresh=force_refresh)
    # Keycloak подписывает RS256; список алгоритмов задан явно, чтобы
    # исключить подмену на "none".
    claims = JsonWebToken(["RS256"]).decode(token, key_set)
    claims.validate()
    return claims


def logout_url(post_logout_redirect_uri: str, id_token: str | None = None) -> str:
    """URL end_session Keycloak — гасит SSO-сессию, а не только нашу cookie."""
    base = (
        f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"
        "/protocol/openid-connect/logout"
    )
    params = [f"post_logout_redirect_uri={post_logout_redirect_uri}"]
    if id_token:
        params.append(f"id_token_hint={id_token}")
    else:
        params.append(f"client_id={settings.keycloak_client_id}")
    return f"{base}?{'&'.join(params)}"
