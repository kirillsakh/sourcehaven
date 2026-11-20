"""Conversations, turns and their sources.

Every function runs inside an `owner_session` for the owner it is given. Each query filters on
that owner explicitly and row-level security limits it to the same owner's rows as well (design
spec section 5.1), so another owner's conversation, turn or document behaves exactly like a
missing one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from sqlalchemy import Row, Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.domain.models import Citation, OwnerScope
from sourcehaven.storage.models import Conversation, Document, DocumentVersion, Turn, TurnSource

FinalTurnStatus = Literal["complete", "interrupted", "failed"]


@dataclass(frozen=True)
class NewTurn:
    """A question turn about to start generating."""

    id: UUID
    owner: OwnerScope
    conversation_id: UUID
    client_request_id: UUID
    question: str
    selected_document_ids: list[UUID]
    model: str | None
    created_at: datetime


@dataclass(frozen=True)
class TurnOutcome:
    """How a generating turn ended.

    Attributes:
        status: The final status.
        text: The answer text, partial unless the status is `complete`.
        error_code: Why the turn did not complete, if it did not.
        input_tokens: Prompt tokens reported by the provider, if any.
        output_tokens: Answer tokens reported by the provider, if any.
        completed_at: When the turn ended.
        sources: Every passage given to the model, stored whatever the status so a document's
            deletion can find the turns that used it. Citation flags are validated only for a
            completed turn; other endings store every passage uncited.
    """

    status: FinalTurnStatus
    text: str
    completed_at: datetime
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    sources: Sequence[Citation] = ()


@dataclass(frozen=True)
class SourceView:
    label: str
    cited: bool
    document_id: UUID | None
    document_name: str
    page_start: int
    page_end: int
    quote: str


@dataclass(frozen=True)
class TurnView:
    id: UUID
    status: str
    question: str | None
    text: str
    created_at: datetime
    sources: list[SourceView]


async def add_conversation(session: AsyncSession, owner: OwnerScope, now: datetime) -> UUID:
    conversation_id: UUID = uuid7()
    session.add(Conversation(id=conversation_id, owner_id=owner.owner_id, created_at=now))
    await session.flush()
    return conversation_id


async def conversation_exists(
    session: AsyncSession, owner: OwnerScope, conversation_id: UUID
) -> bool:
    found: UUID | None = await session.scalar(
        select(Conversation.id).where(
            Conversation.owner_id == owner.owner_id, Conversation.id == conversation_id
        )
    )
    return found is not None


async def document_readiness(
    session: AsyncSession,
    owner: OwnerScope,
    document_ids: Sequence[UUID],
    *,
    lock: bool = False,
) -> dict[UUID, bool]:
    """Map each of the owner's listed documents to whether its current version is ready.

    Ids that are unknown or belong to another owner are absent from the result.

    Args:
        session: Session of the owner's transaction.
        owner: The owner whose documents are listed.
        document_ids: The documents to look up.
        lock: Hold a shared row lock on the found documents until the transaction ends, so that
            a removal of any of them waits for this transaction and cannot slip in between the
            readiness check and the insert of a turn that selects them.
    """
    statement: Select[UUID, str | None] = (
        select(Document.id, DocumentVersion.state)
        .outerjoin(
            DocumentVersion,
            (DocumentVersion.owner_id == owner.owner_id)
            & (DocumentVersion.id == Document.current_version_id),
        )
        .where(Document.owner_id == owner.owner_id, Document.id.in_(document_ids))
    )
    if lock:
        # The version table is outer-joined, so only the documents can be locked.
        statement = statement.with_for_update(read=True, of=Document)
    rows: Sequence[Row[UUID, str | None]] = (await session.execute(statement)).all()
    return {document_id: state == "ready" for document_id, state in rows}


async def find_turn_by_request(
    session: AsyncSession, owner: OwnerScope, conversation_id: UUID, client_request_id: UUID
) -> UUID | None:
    turn_id: UUID | None = await session.scalar(
        select(Turn.id).where(
            Turn.owner_id == owner.owner_id,
            Turn.conversation_id == conversation_id,
            Turn.client_request_id == client_request_id,
        )
    )
    return turn_id


async def find_generating_turn(
    session: AsyncSession, owner: OwnerScope, conversation_id: UUID
) -> UUID | None:
    turn_id: UUID | None = await session.scalar(
        select(Turn.id).where(
            Turn.owner_id == owner.owner_id,
            Turn.conversation_id == conversation_id,
            Turn.status == "generating",
        )
    )
    return turn_id


async def add_generating_turn(session: AsyncSession, new: NewTurn) -> None:
    """Insert a question turn with status `generating`.

    Flushes, so a repeated `client_request_id` or a second generating turn in the conversation
    raises `IntegrityError` here.
    """
    session.add(
        Turn(
            id=new.id,
            owner_id=new.owner.owner_id,
            conversation_id=new.conversation_id,
            client_request_id=new.client_request_id,
            kind="question",
            question=new.question,
            selected_document_ids=new.selected_document_ids,
            status="generating",
            model=new.model,
            created_at=new.created_at,
        )
    )
    await session.flush()


async def finish_turn(
    session: AsyncSession, owner: OwnerScope, turn_id: UUID, outcome: TurnOutcome
) -> bool:
    """Record how a turn ended, unless it has already ended.

    Only a turn that is still `generating` changes, so whichever ending is recorded first wins
    and a later attempt (for example the interruption clean-up after a completed turn) does
    nothing.

    Returns:
        Whether the turn was still generating and has now been updated.
    """
    updated: UUID | None = await session.scalar(
        update(Turn)
        .where(Turn.owner_id == owner.owner_id, Turn.id == turn_id, Turn.status == "generating")
        .values(
            status=outcome.status,
            text=outcome.text,
            error_code=outcome.error_code,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            completed_at=outcome.completed_at,
        )
        .returning(Turn.id)
    )
    if updated is None:
        return False
    session.add_all(
        TurnSource(
            owner_id=owner.owner_id,
            turn_id=turn_id,
            label=citation.label,
            cited=citation.cited,
            document_id=citation.evidence.document_id,
            version_id=citation.evidence.version_id,
            document_name_snapshot=citation.evidence.document_name,
            page_start=citation.evidence.span.start,
            page_end=citation.evidence.span.end,
            quote_snapshot=citation.quote,
        )
        for citation in outcome.sources
    )
    await session.flush()
    return True


def _label_number(source: TurnSource) -> int:
    return int(source.label.removeprefix("S"))


async def list_turns(
    session: AsyncSession, owner: OwnerScope, conversation_id: UUID
) -> list[TurnView]:
    """List a conversation's turns, oldest first, each with its sources ordered by label.

    Only a completed turn has validated sources, so other turns are listed without sources even
    though the passages they were given are stored.
    """
    turns: Sequence[Turn] = (
        await session.scalars(
            select(Turn)
            .where(Turn.owner_id == owner.owner_id, Turn.conversation_id == conversation_id)
            .order_by(Turn.created_at, Turn.id)
        )
    ).all()
    sources: Sequence[TurnSource] = (
        await session.scalars(
            select(TurnSource).where(
                TurnSource.owner_id == owner.owner_id,
                TurnSource.turn_id.in_([turn.id for turn in turns]),
            )
        )
    ).all()
    by_turn: dict[UUID, list[TurnSource]] = {}
    for source in sorted(sources, key=_label_number):
        by_turn.setdefault(source.turn_id, []).append(source)
    return [
        TurnView(
            id=turn.id,
            status=turn.status,
            question=turn.question,
            text=turn.text,
            created_at=turn.created_at,
            sources=[
                SourceView(
                    label=source.label,
                    cited=source.cited,
                    document_id=source.document_id,
                    document_name=source.document_name_snapshot,
                    page_start=source.page_start,
                    page_end=source.page_end,
                    quote=source.quote_snapshot,
                )
                for source in (by_turn.get(turn.id, []) if turn.status == "complete" else [])
            ],
        )
        for turn in turns
    ]
