from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Result, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.models import Chunk


async def count_chunks(session: AsyncSession, owner: OwnerScope, version_id: UUID) -> int:
    result: Result[int] = await session.execute(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.owner_id == owner.owner_id, Chunk.version_id == version_id)
    )
    return result.scalar_one()


async def replace_version_chunks(
    session: AsyncSession, owner: OwnerScope, version_id: UUID, chunks: Sequence[Chunk]
) -> None:
    """Make `chunks` the only chunks of the version, so publishing again never duplicates them.

    The caller's transaction must be an `owner_session` for the version's owner.
    """
    await session.execute(
        delete(Chunk).where(Chunk.owner_id == owner.owner_id, Chunk.version_id == version_id)
    )
    session.add_all(chunks)
    await session.flush()
