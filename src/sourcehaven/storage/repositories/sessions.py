from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, LargeBinary, Result, Row, bindparam, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import TextClause

from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.models import AnonymousSession, Owner


@dataclass(frozen=True)
class SessionRecord:
    """The columns of a stored session that the service needs."""

    session_id: UUID
    owner_id: UUID
    last_active_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


async def add_anonymous_session(
    session: AsyncSession,
    *,
    owner_id: UUID,
    token_hash: bytes,
    now: datetime,
    idle_expires_at: datetime,
    absolute_expires_at: datetime,
) -> None:
    """Insert a new owner and its session.

    Row-level security requires the transaction to be an `owner_session` for `owner_id`.
    """
    session.add(Owner(id=owner_id, kind="anonymous_session"))
    await session.flush()
    session.add(
        AnonymousSession(
            owner_id=owner_id,
            token_hash=token_hash,
            last_active_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )
    )
    await session.flush()


async def resolve_session_owner(
    session: AsyncSession, token_hash: bytes, now: datetime
) -> tuple[UUID, UUID] | None:
    """Look up an active session across owners through the `SECURITY DEFINER` function.

    Returns:
        `(session_id, owner_id)`, or None if the token is unknown, ended or expired.
    """
    statement: TextClause = text(
        "SELECT session_id, owner_id FROM sourcehaven_resolve_session(:token_hash, :now)"
    ).bindparams(
        bindparam("token_hash", type_=LargeBinary),
        bindparam("now", type_=DateTime(timezone=True)),
    )
    result: Result[tuple[UUID, UUID]] = await session.execute(
        statement, {"token_hash": token_hash, "now": now}
    )
    row: Row[tuple[UUID, UUID]] | None = result.one_or_none()
    return None if row is None else (row.session_id, row.owner_id)


async def get_session_record(
    session: AsyncSession, owner: OwnerScope, session_id: UUID
) -> SessionRecord | None:
    """Read one of the owner's sessions."""
    row: AnonymousSession | None = await session.scalar(
        select(AnonymousSession).where(
            AnonymousSession.owner_id == owner.owner_id, AnonymousSession.id == session_id
        )
    )
    if row is None:
        return None
    return SessionRecord(
        session_id=row.id,
        owner_id=row.owner_id,
        last_active_at=row.last_active_at,
        idle_expires_at=row.idle_expires_at,
        absolute_expires_at=row.absolute_expires_at,
    )


async def record_activity(
    session: AsyncSession,
    owner: OwnerScope,
    session_id: UUID,
    *,
    now: datetime,
    idle_expires_at: datetime,
) -> None:
    await session.execute(
        update(AnonymousSession)
        .where(AnonymousSession.owner_id == owner.owner_id, AnonymousSession.id == session_id)
        .values(last_active_at=now, idle_expires_at=idle_expires_at)
    )
