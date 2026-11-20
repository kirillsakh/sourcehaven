from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.storage.models import EmbeddingConfigRow


async def ensure_embedding_config(session: AsyncSession, config: EmbeddingConfig) -> int:
    """Register `config` if it is new and return its id.

    The application role cannot UPDATE `embedding_configs`, so this inserts with
    `ON CONFLICT DO NOTHING` and then reads the id back by fingerprint. A concurrent insert of
    the same fingerprint blocks until it commits, so the read always finds the row.

    Args:
        session: A session in an open transaction; the caller commits.
        config: The configuration to register.

    Returns:
        The id of the row with this configuration's fingerprint.
    """
    fingerprint: str = config.fingerprint()
    await session.execute(
        insert(EmbeddingConfigRow)
        .values(
            fingerprint=fingerprint,
            provider=config.provider,
            model_id=config.model_id,
            model_revision=config.model_revision,
            dimensions=config.dimensions,
            query_prefix=config.query_prefix,
            document_prefix=config.document_prefix,
            normalize=config.normalize,
            max_input_tokens=config.max_input_tokens,
            distance=config.distance,
            chunk_tokens=config.chunk_tokens,
            chunk_overlap=config.chunk_overlap,
        )
        .on_conflict_do_nothing(index_elements=[EmbeddingConfigRow.fingerprint])
    )
    return (
        await session.execute(
            select(EmbeddingConfigRow.id).where(EmbeddingConfigRow.fingerprint == fingerprint)
        )
    ).scalar_one()
