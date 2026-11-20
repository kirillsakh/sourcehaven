import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal, Self

from sourcehaven.config import Settings

HASH_MODEL_ID: str = "hash-bow"
HASH_MODEL_REVISION: str = "1"
HASH_DIMENSIONS: int = 256


@dataclass(frozen=True)
class EmbeddingConfig:
    """Everything that determines which vectors an embedder produces and how text is chunked.

    Stored vectors are only comparable when produced under the same configuration, so the
    fingerprint of all fields identifies the configuration a chunk was embedded with.
    """

    provider: Literal["tei", "hash"]
    model_id: str
    model_revision: str | None
    dimensions: int
    query_prefix: str
    document_prefix: str
    normalize: bool
    max_input_tokens: int
    chunk_tokens: int
    chunk_overlap: int
    distance: Literal["cosine"] = "cosine"

    def fingerprint(self) -> str:
        """Return the SHA-256 hex digest of the sorted-key JSON of every field."""
        canonical: str = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build the configuration for the provider selected in `settings`.

        The `hash` provider ignores the model, dimension and prefix settings because its
        vectors are fixed by the hash embedder itself.
        """
        if settings.embedding_provider == "hash":
            return cls(
                provider="hash",
                model_id=HASH_MODEL_ID,
                model_revision=HASH_MODEL_REVISION,
                dimensions=HASH_DIMENSIONS,
                query_prefix="",
                document_prefix="",
                normalize=True,
                max_input_tokens=settings.embedding_max_input_tokens,
                chunk_tokens=settings.chunk_tokens,
                chunk_overlap=settings.chunk_overlap,
            )
        return cls(
            provider="tei",
            model_id=settings.embedding_model_id,
            model_revision=settings.embedding_model_revision,
            dimensions=settings.embedding_dimensions,
            query_prefix=settings.embedding_query_prefix,
            document_prefix=settings.embedding_document_prefix,
            normalize=True,
            max_input_tokens=settings.embedding_max_input_tokens,
            chunk_tokens=settings.chunk_tokens,
            chunk_overlap=settings.chunk_overlap,
        )
