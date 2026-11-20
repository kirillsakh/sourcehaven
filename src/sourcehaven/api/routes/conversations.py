from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from sourcehaven.api.deps import current_owner, get_container
from sourcehaven.api.errors import ApiError
from sourcehaven.api.schemas import (
    ConversationCreated,
    ConversationResponse,
    PageRange,
    QuestionRequest,
    TurnResponse,
    TurnSourceResponse,
)
from sourcehaven.api.sse import to_server_sent_event
from sourcehaven.composition import AppContainer
from sourcehaven.config import Settings
from sourcehaven.domain.models import OwnerScope
from sourcehaven.qa.service import NotReadyError, QAService, TurnConflictError, TurnStream
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.repositories.conversations import (
    TurnView,
    add_conversation,
    conversation_exists,
    list_turns,
)

router: APIRouter = APIRouter(tags=["conversations"])


def _not_found() -> ApiError:
    return ApiError(404, "not_found")


def _turn_response(turn: TurnView) -> TurnResponse:
    return TurnResponse(
        id=turn.id,
        status=turn.status,
        question=turn.question,
        text=turn.text,
        created_at=turn.created_at,
        sources=[
            TurnSourceResponse(
                label=source.label,
                cited=source.cited,
                document_id=source.document_id,
                document_name=source.document_name,
                pages=PageRange(start=source.page_start, end=source.page_end),
                quote=source.quote,
            )
            for source in turn.sources
        ],
    )


@router.post("", status_code=201)
async def create_conversation(
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> ConversationCreated:
    async with owner_session(container.sessions, owner) as session:
        conversation_id: UUID = await add_conversation(session, owner, container.clock())
    return ConversationCreated(id=conversation_id)


@router.get("/{conversation_id}", responses={404: {"description": "Unknown conversation"}})
async def read_conversation(
    conversation_id: UUID,
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> ConversationResponse:
    """Return the conversation's turns with their stored status, text and sources."""
    async with owner_session(container.sessions, owner) as session:
        if not await conversation_exists(session, owner, conversation_id):
            raise _not_found()
        turns: list[TurnView] = await list_turns(session, owner, conversation_id)
    return ConversationResponse(id=conversation_id, turns=[_turn_response(t) for t in turns])


def _check_limits(settings: Settings, request: QuestionRequest) -> None:
    problems: list[str] = []
    if len(request.question) > settings.max_question_chars:
        problems.append(f"question: at most {settings.max_question_chars} characters")
    if len(request.document_ids) > settings.max_documents_per_question:
        problems.append(f"document_ids: at most {settings.max_documents_per_question} documents")
    if problems:
        raise ApiError(422, "invalid_request", "; ".join(problems))


async def started_turn(
    conversation_id: UUID,
    request: QuestionRequest,
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> AsyncIterator[TurnStream]:
    """Validate and start the turn before the event stream begins, then close it afterwards.

    An `EventSourceResponse` route is an async generator whose body only runs once the response
    has started, so anything it raised could no longer become an HTTP error. This dependency
    runs first; its errors are ordinary JSON responses. Its exit code runs after the response
    has finished or the client has gone (FastAPI's request-scoped dependency exit), and closing
    the stream there stores a turn that is still generating as interrupted.

    Raises:
        ApiError: 422 `invalid_request` beyond the configured limits, 404 `not_found` for an
            unknown or foreign conversation or document, 422 `document_not_ready`, and 409
            `duplicate_request` or `turn_in_progress` with the conflicting `turn_id` when it is
            known.
    """
    _check_limits(container.settings, request)
    try:
        stream: TurnStream = await QAService(container).answer(owner, conversation_id, request)
    except LookupError:
        raise _not_found() from None
    except NotReadyError:
        raise ApiError(422, "document_not_ready") from None
    except TurnConflictError as conflict:
        turn_id: dict[str, str] = (
            {} if conflict.turn_id is None else {"turn_id": str(conflict.turn_id)}
        )
        raise ApiError(409, conflict.code, details=turn_id) from None
    try:
        yield stream
    finally:
        await stream.aclose()


@router.post(
    "/{conversation_id}/turns",
    response_class=EventSourceResponse,
    responses={
        404: {"description": "Unknown conversation or document"},
        409: {"description": "Repeated request, or another turn is generating"},
        422: {"description": "Invalid question, or a document is not ready"},
    },
)
async def ask_question(
    events: Annotated[TurnStream, Depends(started_turn)],
) -> AsyncIterator[ServerSentEvent]:
    """Answer a question as server-sent events: turn, progress, delta..., sources, done or error."""
    async for event in events:
        yield to_server_sent_event(event)
