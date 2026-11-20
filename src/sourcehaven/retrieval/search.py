from collections import Counter
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.domain.models import Evidence, OwnerScope, PageSpan
from sourcehaven.storage.models import Chunk, Document

CANDIDATE_LIMIT: int = 20


async def search_evidence(
    session: AsyncSession,
    *,
    owner: OwnerScope,
    document_ids: Sequence[UUID],
    query_vector: Sequence[float],
    embedding_config_id: int,
    limit: int = CANDIDATE_LIMIT,
) -> list[Evidence]:
    """Find the chunks closest to a query among the owner's selected documents.

    The scan is exact (no approximate index), ordered by cosine distance. Only chunks of each
    document's current version that were embedded with `embedding_config_id` are considered. The
    `owner_id` predicate is explicit although row-level security applies as well; run this inside
    `owner_session` for the same owner so the second layer is active.

    Args:
        session: A session in an `owner_session` transaction for `owner`.
        owner: The only owner whose chunks may be returned.
        document_ids: The selected documents; ids of other owners match nothing.
        query_vector: The embedded query, made with the active embedding configuration.
        embedding_config_id: The active embedding configuration.
        limit: Maximum number of candidates.

    Returns:
        Candidates ordered from the most to the least similar, `1 - cosine distance`.
    """
    if not document_ids:
        return []
    distance: ColumnElement[float] = Chunk.embedding.cosine_distance(list(query_vector))
    statement: Select[UUID, UUID, UUID, str, str, int, int, float] = (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.version_id,
            Document.display_name,
            Chunk.text,
            Chunk.page_start,
            Chunk.page_end,
            (1 - distance).label("similarity"),
        )
        .join(
            Document,
            (Document.id == Chunk.document_id) & (Document.current_version_id == Chunk.version_id),
        )
        .where(
            Chunk.owner_id == owner.owner_id,
            Chunk.document_id.in_(document_ids),
            Chunk.embedding_config_id == embedding_config_id,
        )
        .order_by(distance)
        .limit(limit)
    )
    rows: Sequence[Row[UUID, UUID, UUID, str, str, int, int, float]] = (
        await session.execute(statement)
    ).all()
    return [
        Evidence(
            chunk_id=row.id,
            document_id=row.document_id,
            version_id=row.version_id,
            document_name=row.display_name,
            text=row.text,
            span=PageSpan(start=row.page_start, end=row.page_end),
            similarity=row.similarity,
        )
        for row in rows
    ]


def select_evidence(
    candidates: Sequence[Evidence],
    *,
    max_total: int = 8,
    max_per_document: int = 4,
    threshold: float,
) -> list[Evidence]:
    """Choose the passages to give the model from the retrieved candidates.

    Candidates whose similarity is below `threshold` are dropped; a candidate exactly at the
    threshold is kept. The rest are taken in descending similarity order. When the remaining
    candidates come from more than one document, at most `max_per_document` of them are kept per
    document so a single large document cannot crowd out the others; with one document the cap
    does not apply. At most `max_total` passages are returned.

    Args:
        candidates: Retrieved passages in any order.
        max_total: Maximum number of passages returned.
        max_per_document: Per-document cap, applied only to multi-document evidence.
        threshold: Minimum similarity, inclusive.

    Returns:
        The chosen passages, most similar first; empty when none reaches the threshold.
    """
    passing: list[Evidence] = sorted(
        (candidate for candidate in candidates if candidate.similarity >= threshold),
        key=lambda candidate: candidate.similarity,
        reverse=True,
    )
    capped: bool = len({candidate.document_id for candidate in passing}) > 1
    taken: Counter[UUID] = Counter()
    chosen: list[Evidence] = []
    for candidate in passing:
        if len(chosen) == max_total:
            break
        if capped and taken[candidate.document_id] == max_per_document:
            continue
        taken[candidate.document_id] += 1
        chosen.append(candidate)
    return chosen
