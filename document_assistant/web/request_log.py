"""Лог каждого HTTP-запроса, дошедшего до приложения.

Нужен для разбора ситуаций «502 на Ingress, а в логах пусто»: если строки
``→ GET /...`` нет — запрос до пода не дошёл, проблема в Ingress/прокси.

Пишет две строки на запрос:
    → GET /auth/callback?code=***&state=*** | client=10.0.0.5 xff=... proto=https host=...
    ← 302 GET /auth/callback 41ms | заголовки=5210 Б, set-cookie: da_session_access_token=3100 Б, ...

Значения ``code``, ``state`` и прочих одноразовых параметров маскируются,
значения cookie не пишутся — только имена и размеры. Размеры важны: nginx
по умолчанию не пропускает заголовки ответа больше 4–8 КБ (отдаёт 502 с
``upstream sent too big header``), а браузер молча выбрасывает cookie
больше 4 КБ.

Сделан чистым ASGI-middleware, а не BaseHTTPMiddleware: тот буферизует
ответ и ломает стриминг скачиваемых файлов.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import parse_qsl, urlencode

logger = logging.getLogger("document_assistant.http")

_MASKED_PARAMS = {"code", "state", "session_state", "nonce", "id_token_hint", "token"}
# Пробы Kubernetes дёргают /healthz каждые несколько секунд — только на DEBUG.
_QUIET_PATHS = {"/healthz"}
_HEADERS_WARN_BYTES = 4096
_COOKIE_WARN_BYTES = 4000


def _mask_query(raw: bytes) -> str:
    if not raw:
        return ""
    pairs = parse_qsl(raw.decode("latin-1"), keep_blank_values=True)
    masked = [(k, "***" if k in _MASKED_PARAMS and v else v) for k, v in pairs]
    return "?" + urlencode(masked, safe="*")


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for k, v in headers:
        if k.lower() == name:
            return v.decode("latin-1")
    return "-"


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
        req_headers = scope.get("headers", [])
        client = scope.get("client")
        cookie_header = _header(req_headers, b"cookie")
        logger.log(
            level,
            f"→ {method} {path}{_mask_query(scope.get('query_string', b''))} | "
            f"client={client[0] if client else '-'} "
            f"xff={_header(req_headers, b'x-forwarded-for')} "
            f"proto={_header(req_headers, b'x-forwarded-proto')} "
            f"host={_header(req_headers, b'host')} "
            f"cookies={0 if cookie_header == '-' else len(cookie_header)} Б",
        )

        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                self._log_response(level, method, path, message, started)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            ms = (time.perf_counter() - started) * 1000
            logger.error(f"✗ {method} {path} {ms:.0f}ms | необработанное исключение "
                         f"{type(e).__name__}: {e}", exc_info=True)
            raise

    @staticmethod
    def _log_response(level: int, method: str, path: str, message: dict, started: float) -> None:
        ms = (time.perf_counter() - started) * 1000
        status = message["status"]
        headers = message.get("headers", [])
        headers_size = sum(len(k) + len(v) + 4 for k, v in headers)

        cookies = []
        big_cookie = False
        for k, v in headers:
            if k.lower() == b"set-cookie":
                name = v.split(b"=", 1)[0].decode("latin-1")
                cookies.append(f"{name}={len(v)} Б")
                big_cookie |= len(v) > _COOKIE_WARN_BYTES
        location = _header(headers, b"location")

        parts = [f"заголовки={headers_size} Б"]
        if location != "-":
            parts.append(f"location={location.split('?', 1)[0]}")
        if cookies:
            parts.append("set-cookie: " + ", ".join(cookies))

        line = f"← {status} {method} {path} {ms:.0f}ms | " + " ".join(parts)
        if status >= 500:
            logger.error(line)
        else:
            logger.log(level, line)

        if headers_size > _HEADERS_WARN_BYTES:
            logger.warning(
                f"Заголовки ответа {path} = {headers_size} Б > {_HEADERS_WARN_BYTES} Б. "
                "Ingress-nginx с настройками по умолчанию отдаст на это 502 "
                "(upstream sent too big header) — увеличьте "
                "nginx.ingress.kubernetes.io/proxy-buffer-size.")
        if big_cookie:
            logger.warning(
                f"Cookie в ответе {path} больше {_COOKIE_WARN_BYTES} Б — браузер может её "
                "не сохранить, что даст бесконечный редирект на логин.")
