import hashlib
import math
import re
from collections.abc import Sequence

from sourcehaven.embeddings.config import (
    HASH_DIMENSIONS,
    HASH_MODEL_ID,
    HASH_MODEL_REVISION,
    EmbeddingConfig,
)

_NON_WORD: re.Pattern[str] = re.compile(r"\W+")


class HashEmbedder:
    """Deterministic offline bag-of-words embedder for tests and local development.

    Each lowercased word adds 1.0 to the dimension chosen by its BLAKE2b hash, and the vector
    is L2-normalised, so texts that share words have a higher cosine similarity.
    """

    def __init__(
        self, dimensions: int = HASH_DIMENSIONS, *, config: EmbeddingConfig | None = None
    ) -> None:
        """Create the embedder.

        Args:
            dimensions: Vector length.
            config: Configuration to report. Defaults to the hash provider's fixed values with
                the default token limits; pass the configuration built from settings so that
                chunking limits match the rest of the application.

        Raises:
            ValueError: If `dimensions` is not positive or `config` disagrees with it.
        """
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        resolved: EmbeddingConfig = config or EmbeddingConfig(
            provider="hash",
            model_id=HASH_MODEL_ID,
            model_revision=HASH_MODEL_REVISION,
            dimensions=dimensions,
            query_prefix="",
            document_prefix="",
            normalize=True,
            max_input_tokens=2048,
            chunk_tokens=400,
            chunk_overlap=60,
        )
        if resolved.dimensions != dimensions:
            raise ValueError("config.dimensions must equal dimensions")
        self._dimensions: int = dimensions
        self._config: EmbeddingConfig = resolved

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def check_ready(self) -> None:
        return None

    def _embed(self, text: str) -> list[float]:
        vector: list[float] = [0.0] * self._dimensions
        for token in _NON_WORD.split(text.lower()):
            if token:
                digest: bytes = hashlib.blake2b(token.encode(), digest_size=8).digest()
                vector[int.from_bytes(digest, "big") % self._dimensions] += 1.0
        norm: float = math.sqrt(math.fsum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class WhitespaceTokenCounter:
    def count(self, text: str) -> int:
        return len(text.split())
