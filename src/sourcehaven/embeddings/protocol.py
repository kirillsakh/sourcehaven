from collections.abc import Sequence
from typing import Protocol

from sourcehaven.embeddings.config import EmbeddingConfig


class EmbedderNotReady(Exception):
    """The embedding service is unreachable or serves a different model than configured."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


class EmbedderUnavailable(Exception):
    """The embedding service failed to produce vectors: timeout, connection error or 5xx."""


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class Embedder(Protocol):
    @property
    def config(self) -> EmbeddingConfig: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def check_ready(self) -> None:
        """Return when the embedder can serve requests.

        Raises:
            EmbedderNotReady: If the service is unreachable or does not match the config.
        """
        ...
