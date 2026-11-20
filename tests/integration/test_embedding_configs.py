from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.storage.db import system_session
from sourcehaven.storage.repositories.embedding_configs import ensure_embedding_config
from tests.support.embeddings import make_config

pytestmark = pytest.mark.integration


async def _ensure(sessions: async_sessionmaker[AsyncSession], config: EmbeddingConfig) -> int:
    async with system_session(sessions) as session:
        return await ensure_embedding_config(session, config)


async def test_ensure_embedding_config_is_idempotent_per_fingerprint(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    config: EmbeddingConfig = make_config()
    first: int = await _ensure(app_sessions, config)
    assert await _ensure(app_sessions, config) == first
    changed: int = await _ensure(app_sessions, replace(config, model_revision="rev-2"))
    assert changed != first
