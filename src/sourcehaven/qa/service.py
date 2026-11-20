import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID, uuid7

import anyio
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.api.schemas import QuestionRequest
from sourcehaven.composition import AppContainer
from sourcehaven.config import Settings
from sourcehaven.domain.models import Citation, Evidence, OwnerScope
from sourcehaven.generation.prompts import (
    LabelledEvidence,
    PromptBudget,
    assemble_answer_messages,
)
from sourcehaven.qa.citations import CitationResult, validate_citations
from sourcehaven.qa.events import (
    Delta,
    Done,
    Failed,
    Progress,
    SourcesFinal,
    TurnEvent,
    TurnStarted,
)
from sourcehaven.retrieval.search import search_evidence, select_evidence
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.repositories.conversations import (
    NewTurn,
    TurnOutcome,
    add_generating_turn,
    conversation_exists,
    document_readiness,
    find_generating_turn,
    find_turn_by_request,
    finish_turn,
)

logger: logging.Logger = logging.getLogger(__name__)

NO_EVIDENCE_ANSWER: Final[str] = "I couldn't find information about this in the selected documents."
RETRY_MESSAGE: Final[str] = "The answer could not be completed. Please try again."
LENGTH_LIMIT_MESSAGE: Final[str] = (
    "This answer was cut off because it reached the length limit. Please try again."
)
# A conflicting insert whose competing turn has ended by the re-check is tried once more.
TURN_INSERT_ATTEMPTS: Final[int] = 2

# Strong references to interruption writes: a task the event loop only references weakly could
# be garbage-collected before it finishes.
_pending_writes: set[asyncio.Task[bool]] = set()


class NotReadyError(Exception):
    """Some selected documents have no ready current version yet."""

    def __init__(self, document_ids: Sequence[UUID]) -> None:
        super().__init__("Selected documents are not ready")
        self.document_ids: list[UUID] = list(document_ids)


class TurnConflictError(Exception):
    """The turn cannot start because of another turn in the same conversation.

    Attributes:
        code: `duplicate_request` when the client request id was already used in the
            conversation; `turn_in_progress` when another turn is still generating, or kept
            colliding with turns that ended before they could be identified.
        turn_id: The existing turn the conflict is with, when it is known.
    """

    def __init__(
        self, code: Literal["duplicate_request", "turn_in_progress"], turn_id: UUID | None
    ) -> None:
        super().__init__(code)
        self.code: Literal["duplicate_request", "turn_in_progress"] = code
        self.turn_id: UUID | None = turn_id


@dataclass(frozen=True)
class _StartedTurn:
    turn_id: UUID
    owner: OwnerScope
    question: str
    document_ids: list[UUID]


class TurnStream:
    """The events of one started turn.

    Iterate it to drive the answer. Close it with `aclose()` once it will not be consumed to the
    end, including when it was never iterated: closing stores a turn that is still generating as
    `interrupted`.
    """

    def __init__(self, first: TurnEvent, rest: AsyncGenerator[TurnEvent]) -> None:
        self._first: TurnEvent | None = first
        self._rest: AsyncGenerator[TurnEvent] = rest

    def __aiter__(self) -> TurnStream:
        return self

    async def __anext__(self) -> TurnEvent:
        if self._first is not None:
            first: TurnEvent = self._first
            self._first = None
            return first
        return await anext(self._rest)

    async def aclose(self) -> None:
        await self._rest.aclose()


@asynccontextmanager
async def _closing[T](stream: AsyncIterator[T]) -> AsyncIterator[AsyncIterator[T]]:
    # Closing the model stream promptly releases the upstream provider connection.
    try:
        yield stream
    finally:
        if isinstance(stream, AsyncGenerator):
            await stream.aclose()


def _unvalidated(supplied: Sequence[LabelledEvidence]) -> list[Citation]:
    """The supplied passages of an incomplete answer, none of them marked cited."""
    return [Citation(label=item.label, evidence=item.evidence, cited=False) for item in supplied]


class QAService:
    """Answers questions about an owner's selected documents with validated citations."""

    def __init__(self, container: AppContainer) -> None:
        self._container: AppContainer = container

    async def answer(
        self, owner: OwnerScope, conversation_id: UUID, request: QuestionRequest
    ) -> TurnStream:
        """Start a question turn and return the stream of its events.

        Awaiting this runs every check that can reject the request and inserts the turn row,
        so rejections are raised before any event exists and can be ordinary HTTP errors.
        Iterating the returned stream then yields `TurnStarted`, `Progress("retrieving")`,
        `Delta`s, and finally `SourcesFinal` and `Done`, or `Failed`. Every ending is stored on
        the turn before its final event is produced.

        Client disconnects (verified against the installed FastAPI 0.165.0 and Starlette 1.10.0
        source, since the FastAPI SSE tutorial does not describe disconnects): an
        `EventSourceResponse` route's generator is iterated by a producer task inside an anyio
        task group entered on the request-scoped exit stack (`fastapi/routing.py`,
        `_sse_producer_cm`). Starlette's `StreamingResponse` notices the disconnect by receiving
        `http.disconnect` (uvicorn's HTTP protocols declare ASGI spec 2.3; for spec >= 2.4 a
        failing `send` raises `OSError` instead) and cancels its streaming task group
        (`starlette/responses.py`, `StreamingResponse.__call__`). The handler then returns, the
        exit stack unwinds, and `_sse_producer_cm` cancels the producer's task group, so this
        stream receives `asyncio.CancelledError` at whatever it awaits; if it is suspended at a
        `yield` instead, `TurnStream.aclose()` (called by the route's dependency during the same
        unwinding) raises `GeneratorExit` there. Either way the `finally` block stores the
        partial text as `interrupted`. That write runs in a fresh owner transaction inside an
        anyio shielded cancel scope, because anyio re-delivers the cancellation at every await
        in the cancelled task group, and awaits it through `asyncio.shield`, so a plain asyncio
        cancellation of the request task cannot abandon the write either.

        Args:
            owner: The visitor's owner scope.
            conversation_id: The conversation to add the turn to.
            request: The validated question.

        Returns:
            The turn's events; the turn is already stored as `generating`.

        Raises:
            LookupError: If the conversation or any selected document does not exist for this
                owner; another owner's ids are reported identically to unknown ones.
            NotReadyError: If a selected document has no ready current version.
            TurnConflictError: If the client request id was already used in the conversation,
                or another turn in it is still generating (or, twice in a row, was generating
                when the turn was inserted but had ended by the re-check).
        """
        started: _StartedTurn = await self._start(owner, conversation_id, request)
        events: AsyncGenerator[TurnEvent] = self._events(started)
        # Running to the first event enters the generator's try block, so closing the stream
        # from now on always reaches the clean-up that ends the turn.
        first: TurnEvent = await anext(events)
        return TurnStream(first, events)

    async def _start(
        self, owner: OwnerScope, conversation_id: UUID, request: QuestionRequest
    ) -> _StartedTurn:
        document_ids: list[UUID] = list(dict.fromkeys(request.document_ids))
        new: NewTurn = NewTurn(
            id=uuid7(),
            owner=owner,
            conversation_id=conversation_id,
            client_request_id=request.client_request_id,
            question=request.question,
            selected_document_ids=document_ids,
            model=self._model_name(),
            created_at=self._container.clock(),
        )
        for _attempt in range(TURN_INSERT_ATTEMPTS):
            try:
                async with owner_session(self._container.sessions, owner) as session:
                    await self._check_scope(session, owner, conversation_id, document_ids)
                    await self._raise_if_conflicting(session, owner, conversation_id, request)
                    await add_generating_turn(session, new)
                break
            except IntegrityError:
                # A concurrent request inserted its turn between the checks and the insert.
                async with owner_session(self._container.sessions, owner) as session:
                    await self._raise_if_conflicting(session, owner, conversation_id, request)
                logger.warning(
                    "turn insert in conversation %s collided with a turn that has since ended",
                    conversation_id,
                )
        else:
            raise TurnConflictError("turn_in_progress", None)
        logger.info("turn %s started in conversation %s", new.id, conversation_id)
        return _StartedTurn(
            turn_id=new.id, owner=owner, question=request.question, document_ids=document_ids
        )

    @staticmethod
    async def _check_scope(
        session: AsyncSession,
        owner: OwnerScope,
        conversation_id: UUID,
        document_ids: Sequence[UUID],
    ) -> None:
        if not await conversation_exists(session, owner, conversation_id):
            raise LookupError("conversation")
        readiness: dict[UUID, bool] = await document_readiness(
            session, owner, document_ids, lock=True
        )
        if len(readiness) != len(document_ids):
            raise LookupError("document")
        not_ready: list[UUID] = [key for key in document_ids if not readiness[key]]
        if not_ready:
            raise NotReadyError(not_ready)

    @staticmethod
    async def _raise_if_conflicting(
        session: AsyncSession, owner: OwnerScope, conversation_id: UUID, request: QuestionRequest
    ) -> None:
        existing: UUID | None = await find_turn_by_request(
            session, owner, conversation_id, request.client_request_id
        )
        if existing is not None:
            raise TurnConflictError("duplicate_request", existing)
        generating: UUID | None = await find_generating_turn(session, owner, conversation_id)
        if generating is not None:
            raise TurnConflictError("turn_in_progress", generating)

    def _model_name(self) -> str | None:
        settings: Settings = self._container.settings
        return settings.openai_model if settings.generation_provider == "openai" else None

    async def _events(self, turn: _StartedTurn) -> AsyncGenerator[TurnEvent]:
        parts: list[str] = []
        # Passages sent to the model are stored with every ending, so deleting a document can
        # find each turn that used it; only a completed turn's citation flags are validated.
        supplied: list[LabelledEvidence] = []
        ended: bool = False
        try:
            yield TurnStarted(turn.turn_id)
            yield Progress("retrieving")
            evidence: list[Evidence] = await self._retrieve(turn)
            if not evidence:
                parts.append(NO_EVIDENCE_ANSWER)
                yield Delta(NO_EVIDENCE_ANSWER)
                await self._finish(turn, TurnOutcome("complete", NO_EVIDENCE_ANSWER, self._now()))
                ended = True
                yield SourcesFinal(CitationResult(sources=[], invalid_labels=[]))
                yield Done(None, None)
                return
            messages: list[BaseMessage]
            labelled: list[LabelledEvidence]
            messages, labelled = assemble_answer_messages(
                turn.question,
                evidence,
                budget=PromptBudget(),
                count_tokens=self._container.count_prompt_tokens,
            )
            usage: UsageMetadata | None = None
            finish_reason: str | None = None
            supplied = labelled
            try:
                async with _closing(self._container.chat_model.astream(messages)) as stream:
                    async for chunk in stream:
                        if isinstance(chunk, AIMessageChunk) and chunk.usage_metadata:
                            usage = chunk.usage_metadata
                        reason: object = chunk.response_metadata.get("finish_reason")
                        if isinstance(reason, str):
                            finish_reason = reason
                        piece: str = str(chunk.text)
                        if piece:
                            parts.append(piece)
                            yield Delta(piece)
            except Exception as error:
                logger.warning("turn %s generation failed: %s", turn.turn_id, type(error).__name__)
                await self._finish(
                    turn,
                    TurnOutcome(
                        "failed",
                        "".join(parts),
                        self._now(),
                        error_code="provider_error",
                        sources=_unvalidated(supplied),
                    ),
                )
                ended = True
                yield Failed("failed", "provider_error", RETRY_MESSAGE, True)
                return
            text: str = "".join(parts)
            input_tokens: int | None = None if usage is None else usage["input_tokens"]
            output_tokens: int | None = None if usage is None else usage["output_tokens"]
            # A reasoning model can spend its whole output budget before writing anything, and
            # an answer cut off by the limit may lack its citations: neither is a complete answer.
            unfinished: Failed | None = None
            if not text.strip():
                unfinished = Failed("failed", "empty_answer", RETRY_MESSAGE, True)
            elif finish_reason == "length":
                unfinished = Failed("interrupted", "length_limit", LENGTH_LIMIT_MESSAGE, True)
            if unfinished is not None:
                await self._finish(
                    turn,
                    TurnOutcome(
                        unfinished.status,
                        text,
                        self._now(),
                        error_code=unfinished.code,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        sources=_unvalidated(supplied),
                    ),
                )
                ended = True
                logger.warning(
                    "turn %s ended without a complete answer: %s", turn.turn_id, unfinished.code
                )
                yield unfinished
                return
            result: CitationResult = validate_citations(text, labelled)
            await self._finish(
                turn,
                TurnOutcome(
                    "complete",
                    text,
                    self._now(),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    sources=result.sources,
                ),
            )
            ended = True
            logger.info(
                "turn %s complete with %d sources and %d invalid citation labels",
                turn.turn_id,
                len(result.sources),
                len(result.invalid_labels),
            )
            yield SourcesFinal(result)
            yield Done(input_tokens, output_tokens)
        except Exception as error:
            if ended:
                raise
            logger.warning("turn %s failed: %s", turn.turn_id, type(error).__name__)
            await self._finish(
                turn,
                TurnOutcome(
                    "failed",
                    "".join(parts),
                    self._now(),
                    error_code="internal_error",
                    sources=_unvalidated(supplied),
                ),
            )
            ended = True
            yield Failed("failed", "internal_error", RETRY_MESSAGE, True)
        finally:
            if not ended:
                await self._store_interrupted(turn, "".join(parts), _unvalidated(supplied))

    async def _retrieve(self, turn: _StartedTurn) -> list[Evidence]:
        query_vector: list[float] = await self._container.embedder.embed_query(turn.question)
        async with owner_session(self._container.sessions, turn.owner) as session:
            candidates: list[Evidence] = await search_evidence(
                session,
                owner=turn.owner,
                document_ids=turn.document_ids,
                query_vector=query_vector,
                embedding_config_id=self._container.embedding_config_id,
            )
        return select_evidence(candidates, threshold=self._container.settings.evidence_threshold)

    def _now(self) -> datetime:
        return self._container.clock()

    async def _finish(self, turn: _StartedTurn, outcome: TurnOutcome) -> bool:
        async with owner_session(self._container.sessions, turn.owner) as session:
            return await finish_turn(session, turn.owner, turn.turn_id, outcome)

    async def _store_interrupted(
        self, turn: _StartedTurn, text: str, sources: Sequence[Citation]
    ) -> None:
        outcome: TurnOutcome = TurnOutcome("interrupted", text, self._now(), sources=sources)
        write: asyncio.Task[bool] = asyncio.ensure_future(self._finish(turn, outcome))
        _pending_writes.add(write)
        write.add_done_callback(_pending_writes.discard)
        try:
            with anyio.CancelScope(shield=True):
                stored: bool = await asyncio.shield(write)
        except Exception as error:
            logger.error(
                "turn %s could not be stored as interrupted: %s",
                turn.turn_id,
                type(error).__name__,
            )
            return
        if stored:
            logger.info("turn %s interrupted", turn.turn_id)
