"""HTML-страницы: загрузка, история, статус.

Статус обновляется HTMX-поллингом: страница раз в 2 секунды подтягивает
фрагмент ``/pages/sessions/{id}/status`` и подменяет им блок. Когда сессия
дошла до done или error, фрагмент отдаётся с ``hx-swap-oob`` и поллинг
останавливается — HTMX прекращает опрос, если в ответе нет hx-trigger.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from document_assistant.auth.dependencies import CurrentUser, require_user_page
from document_assistant.db.models import SessionStatus
from document_assistant.db.repository import SessionRepository
from document_assistant.storage import storage
from document_assistant.web.deps import get_db, templates

router = APIRouter(tags=["pages"])


@router.get("/", name="index_page")
async def index(
    request: Request,
    user: CurrentUser = Depends(require_user_page),
    db: AsyncSession = Depends(get_db),
):
    sessions = await SessionRepository(db).list_for_user(user.user_id)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "sessions": sessions},
    )


@router.get("/sessions/{session_id}", name="session_page")
async def session_page(
    session_id: str,
    request: Request,
    user: CurrentUser = Depends(require_user_page),
    db: AsyncSession = Depends(get_db),
):
    session = await SessionRepository(db).get_for_user(session_id, user.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return templates.TemplateResponse(
        request,
        "session.html",
        {"user": user, "session": session},
    )


@router.get("/pages/sessions/{session_id}/status", name="session_status_fragment")
async def session_status_fragment(
    session_id: str,
    request: Request,
    user: CurrentUser = Depends(require_user_page),
    db: AsyncSession = Depends(get_db),
):
    """HTMX-фрагмент со статусом. Тот же фильтр по user_id, что и в API."""
    session = await SessionRepository(db).get_for_user(session_id, user.user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    download_url = None
    if session.status is SessionStatus.DONE and session.output_key:
        download_url = storage.presigned_url(session.output_key)

    return templates.TemplateResponse(
        request,
        "partials/status.html",
        {"session": session, "download_url": download_url},
    )
