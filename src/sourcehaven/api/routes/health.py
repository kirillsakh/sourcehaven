import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from sourcehaven.api.deps import get_container
from sourcehaven.composition import AppContainer
from sourcehaven.embeddings.protocol import EmbedderNotReady
from sourcehaven.migrations import packaged_head
from sourcehaven.storage.db import system_session

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(tags=["health"])

NotReadyReason = Literal["database", "migrations", "embeddings"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


class NotReadyResponse(BaseModel):
    status: Literal["not_ready"] = "not_ready"
    reason: NotReadyReason


@router.get("/live")
async def live() -> LiveResponse:
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": NotReadyResponse}})
async def ready(
    container: Annotated[AppContainer, Depends(get_container)],
) -> ReadyResponse | JSONResponse:
    reason: NotReadyReason | None = await _first_failure(container)
    if reason is None:
        return ReadyResponse()
    return JSONResponse(NotReadyResponse(reason=reason).model_dump(), status_code=503)


async def _first_failure(container: AppContainer) -> NotReadyReason | None:
    try:
        async with system_session(container.sessions) as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError, OSError:
        logger.warning("Readiness: database is unreachable", exc_info=True)
        return "database"
    try:
        async with system_session(container.sessions) as session:
            revision: str | None = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
    except SQLAlchemyError:
        logger.warning("Readiness: the applied migration revision cannot be read", exc_info=True)
        return "migrations"
    if revision != packaged_head():
        logger.warning("Readiness: database revision %s is not %s", revision, packaged_head())
        return "migrations"
    try:
        await container.embedder.check_ready()
    except EmbedderNotReady as error:
        logger.warning("Readiness: embeddings are not ready: %s", error.reason)
        return "embeddings"
    return None
