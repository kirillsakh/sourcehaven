import math
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from sourcehaven.api.deps import (
    SESSION_COOKIE,
    current_session,
    get_container,
    get_session_service,
    optional_session,
)
from sourcehaven.api.errors import ApiError
from sourcehaven.api.schemas import SessionCreateRequest, SessionLimits, SessionResponse
from sourcehaven.composition import AppContainer
from sourcehaven.sessions.service import CreatedSession, ResolvedSession, SessionService

router: APIRouter = APIRouter(tags=["session"])


def _response(
    container: AppContainer, idle_expires_at: datetime, absolute_expires_at: datetime
) -> SessionResponse:
    return SessionResponse(
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        limits=SessionLimits(
            max_documents=container.settings.max_documents_per_session,
            max_pages_per_document=container.settings.max_pages_per_document,
            max_upload_bytes=container.settings.max_upload_bytes,
            max_question_chars=container.settings.max_question_chars,
        ),
    )


@router.post("", responses={403: {"description": "Human verification failed"}})
async def create_session(
    request: Request,
    response: Response,
    container: Annotated[AppContainer, Depends(get_container)],
    service: Annotated[SessionService, Depends(get_session_service)],
    existing: Annotated[ResolvedSession | None, Depends(optional_session)],
    body: SessionCreateRequest | None = None,
) -> SessionResponse:
    """Start an anonymous session, or return the one the cookie already identifies."""
    if existing is not None:
        return _response(container, existing.idle_expires_at, existing.absolute_expires_at)
    verification_token: str | None = None if body is None else body.verification_token
    remote_ip: str | None = None if request.client is None else request.client.host
    if not await container.verifier.verify(verification_token, remote_ip):
        raise ApiError(403, "verification_failed")
    created: CreatedSession = await service.create()
    response.set_cookie(
        SESSION_COOKIE,
        created.token,
        max_age=math.ceil((created.absolute_expires_at - container.clock()).total_seconds()),
        httponly=True,
        secure=container.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return _response(container, created.idle_expires_at, created.absolute_expires_at)


@router.get("", responses={401: {"description": "No active session"}})
async def read_session(
    container: Annotated[AppContainer, Depends(get_container)],
    session: Annotated[ResolvedSession, Depends(current_session)],
) -> SessionResponse:
    return _response(container, session.idle_expires_at, session.absolute_expires_at)
