from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid7

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sourcehaven.domain.models import OwnerScope
from sourcehaven.sessions.tokens import hash_token, new_token
from sourcehaven.storage.db import owner_session, system_session
from sourcehaven.storage.repositories.sessions import (
    SessionRecord,
    add_anonymous_session,
    get_session_record,
    record_activity,
    resolve_session_owner,
)

ACTIVITY_TOUCH_INTERVAL: timedelta = timedelta(minutes=1)


@dataclass(frozen=True)
class CreatedSession:
    token: str
    owner: OwnerScope
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True)
class ResolvedSession:
    session_id: UUID
    owner: OwnerScope
    idle_expires_at: datetime
    absolute_expires_at: datetime


class SessionService:
    """Creates anonymous server-side sessions and resolves their tokens to owners."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        idle: timedelta,
        absolute: timedelta,
    ) -> None:
        self._sessions: async_sessionmaker[AsyncSession] = sessions
        self._clock: Callable[[], datetime] = clock
        self._idle: timedelta = idle
        self._absolute: timedelta = absolute

    async def create(self) -> CreatedSession:
        """Create an owner and a session for it.

        The idle expiry never extends beyond the absolute expiry.
        """
        now: datetime = self._clock()
        absolute_expires_at: datetime = now + self._absolute
        idle_expires_at: datetime = min(now + self._idle, absolute_expires_at)
        owner: OwnerScope = OwnerScope(owner_id=uuid7())
        token: str = new_token()
        async with owner_session(self._sessions, owner) as session:
            await add_anonymous_session(
                session,
                owner_id=owner.owner_id,
                token_hash=hash_token(token),
                now=now,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=absolute_expires_at,
            )
        return CreatedSession(
            token=token,
            owner=owner,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
        )

    async def resolve(self, token: str) -> ResolvedSession | None:
        """Return the active session for `token`, extending its idle expiry.

        Activity is recorded at most once per `ACTIVITY_TOUCH_INTERVAL`, and the extended idle
        expiry is capped at the absolute expiry.

        Returns:
            The session, or None if the token is unknown, ended or expired.
        """
        now: datetime = self._clock()
        async with system_session(self._sessions) as session:
            found: tuple[UUID, UUID] | None = await resolve_session_owner(
                session, hash_token(token), now
            )
        if found is None:
            return None
        session_id, owner_id = found
        owner: OwnerScope = OwnerScope(owner_id=owner_id)
        async with owner_session(self._sessions, owner) as session:
            record: SessionRecord | None = await get_session_record(session, owner, session_id)
            if record is None:
                return None
            idle_expires_at: datetime = record.idle_expires_at
            if now - record.last_active_at >= ACTIVITY_TOUCH_INTERVAL:
                idle_expires_at = min(now + self._idle, record.absolute_expires_at)
                await record_activity(
                    session, owner, session_id, now=now, idle_expires_at=idle_expires_at
                )
        return ResolvedSession(
            session_id=session_id,
            owner=owner,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=record.absolute_expires_at,
        )
