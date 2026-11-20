from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request

from sourcehaven.api.errors import ApiError
from sourcehaven.composition import AppContainer
from sourcehaven.config import Settings
from sourcehaven.domain.models import OwnerScope
from sourcehaven.sessions.service import ResolvedSession, SessionService

SESSION_COOKIE: str = "sh_session"
# Missing, unknown and expired sessions are rejected identically.
SESSION_REQUIRED: str = "session_required"


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


def get_session_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> SessionService:
    settings: Settings = container.settings
    return SessionService(
        container.sessions,
        container.clock,
        idle=timedelta(hours=settings.session_idle_hours),
        absolute=timedelta(days=settings.session_absolute_days),
    )


async def optional_session(
    request: Request, service: Annotated[SessionService, Depends(get_session_service)]
) -> ResolvedSession | None:
    token: str | None = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await service.resolve(token)


async def current_session(
    session: Annotated[ResolvedSession | None, Depends(optional_session)],
) -> ResolvedSession:
    if session is None:
        raise ApiError(401, SESSION_REQUIRED)
    return session


async def optional_owner(
    session: Annotated[ResolvedSession | None, Depends(optional_session)],
) -> OwnerScope | None:
    return None if session is None else session.owner


async def current_owner(
    session: Annotated[ResolvedSession, Depends(current_session)],
) -> OwnerScope:
    return session.owner
