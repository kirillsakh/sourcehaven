from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from tokenizers import Tokenizer

from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.protocol import EmbedderNotReady, EmbedderUnavailable

# TEI answers 429 when its request queue is full; the request is worth retrying later.
_RETRYABLE_CLIENT_ERROR: int = 429


class TeiEmbedder:
    """Embedder backed by a Hugging Face Text Embeddings Inference server.

    Requests are sent with `truncate: false`, so an input longer than the server's token limit
    is rejected instead of silently cut. Chunking must therefore stay within
    `config.max_input_tokens`, which has to equal the server's `--max-batch-tokens`.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: EmbeddingConfig,
        batch_size: int = 32,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Create the embedder.

        Args:
            client: Client whose `base_url` is the TEI server; the caller owns its lifecycle.
            config: The configuration the server is expected to serve.
            batch_size: Maximum number of texts per `/embed` request.
            timeout_seconds: Timeout applied to every request.
        """
        self._client: httpx.AsyncClient = client
        self._config: EmbeddingConfig = config
        self._batch_size: int = batch_size
        self._timeout_seconds: float = timeout_seconds

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed document texts in batches.

        Raises:
            EmbedderUnavailable: On timeouts, connection errors, 5xx and 429 responses, or a
                malformed response.
            httpx.HTTPStatusError: On any other error status, which indicates a bad request.
        """
        return await self._embed(texts, self._config.document_prefix)

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query text; raises like `embed_documents`."""
        return (await self._embed([text], self._config.query_prefix))[0]

    async def check_ready(self) -> None:
        """Verify the server is reachable and serves the configured model and revision.

        Raises:
            EmbedderNotReady: If the server cannot be reached or reports a different model.
        """
        try:
            response: httpx.Response = await self._client.get(
                "/info", timeout=self._timeout_seconds
            )
            response.raise_for_status()
            info: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbedderNotReady(f"TEI is unreachable: {error!r}") from error
        if info.get("model_id") != self._config.model_id:
            raise EmbedderNotReady(
                f"TEI serves model {info.get('model_id')!r}, expected {self._config.model_id!r}"
            )
        if info.get("model_sha") != self._config.model_revision:
            raise EmbedderNotReady(
                f"TEI serves revision {info.get('model_sha')!r}, "
                f"expected {self._config.model_revision!r}"
            )

    async def _embed(self, texts: Sequence[str], prefix: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch: list[str] = [prefix + text for text in texts[start : start + self._batch_size]]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        try:
            response: httpx.Response = await self._client.post(
                "/embed",
                json={"inputs": inputs, "normalize": self._config.normalize, "truncate": False},
                timeout=self._timeout_seconds,
            )
        except httpx.TransportError as error:
            raise EmbedderUnavailable(f"TEI request failed: {error!r}") from error
        if response.status_code >= 500 or response.status_code == _RETRYABLE_CLIENT_ERROR:
            raise EmbedderUnavailable(f"TEI answered with status {response.status_code}")
        response.raise_for_status()
        try:
            vectors: list[list[float]] = response.json()
        except ValueError as error:
            raise EmbedderUnavailable("TEI answered with invalid JSON") from error
        if len(vectors) != len(inputs) or any(
            len(vector) != self._config.dimensions for vector in vectors
        ):
            raise EmbedderUnavailable(
                f"TEI returned vectors that do not match {len(inputs)} inputs "
                f"of {self._config.dimensions} dimensions"
            )
        return vectors


class HfTokenCounter:
    """Counts tokens with a Hugging Face `tokenizer.json`, excluding special tokens."""

    def __init__(self, tokenizer_file: Path) -> None:
        self._tokenizer: Tokenizer = Tokenizer.from_file(str(tokenizer_file))

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
