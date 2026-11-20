import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from typing import TypedDict

import httpx

from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.hashing import HashEmbedder
from sourcehaven.embeddings.protocol import EmbedderNotReady, EmbedderUnavailable
from sourcehaven.embeddings.tei import TeiEmbedder
from sourcehaven.ingestion.errors import IngestionError

TEST_MODEL_ID: str = "test/model"
TEST_MODEL_REVISION: str = "rev-1"


class TeiRequest(TypedDict):
    inputs: list[str]
    normalize: bool
    truncate: bool


def make_config(dimensions: int = 768) -> EmbeddingConfig:
    return EmbeddingConfig(
        provider="tei",
        model_id=TEST_MODEL_ID,
        model_revision=TEST_MODEL_REVISION,
        dimensions=dimensions,
        query_prefix="query: ",
        document_prefix="",
        normalize=True,
        max_input_tokens=2048,
        chunk_tokens=400,
        chunk_overlap=60,
    )


def cosine(left: list[float], right: list[float]) -> float:
    dot: float = math.fsum(a * b for a, b in zip(left, right, strict=True))
    norms: float = math.sqrt(math.fsum(a * a for a in left)) * math.sqrt(
        math.fsum(b * b for b in right)
    )
    return dot / norms


def tei_mock(seen: list[TeiRequest], *, dimensions: int) -> httpx.MockTransport:
    """Fake TEI that records `/embed` request bodies and answers with constant vectors."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(200, json=tei_info())
        body: TeiRequest = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json=[[0.5] * dimensions for _ in body["inputs"]])

    return httpx.MockTransport(handle)


def tei_info(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    info: dict[str, str] = {"model_id": TEST_MODEL_ID, "model_sha": TEST_MODEL_REVISION}
    info.update(overrides or {})
    return info


def tei_with_info(overrides: Mapping[str, str]) -> TeiEmbedder:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tei_info(overrides))

    client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://tei"
    )
    return TeiEmbedder(client, make_config())


def tei_with_response(response: httpx.Response | Exception) -> TeiEmbedder:
    """TEI that answers every request with `response`, or raises it when it is an exception."""

    def handle(_request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    client: httpx.AsyncClient = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://tei"
    )
    return TeiEmbedder(client, make_config(dimensions=3))


class NotReadyEmbedder:
    """Embedder whose service never matches the configured model."""

    def __init__(self) -> None:
        self._config: EmbeddingConfig = make_config()

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbedderNotReady("not ready")

    async def embed_query(self, text: str) -> list[float]:
        raise EmbedderNotReady("not ready")

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbedderNotReady("not ready")

    async def check_ready(self) -> None:
        raise EmbedderNotReady("serves a different model")


class FailingEmbedder:
    """Embedder whose service is always down, as the pipeline sees an outage."""

    def __init__(self) -> None:
        self._config: EmbeddingConfig = make_config()

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise IngestionError("embedding_unavailable", retryable=True)

    async def embed_query(self, text: str) -> list[float]:
        raise IngestionError("embedding_unavailable", retryable=True)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise IngestionError("embedding_unavailable", retryable=True)

    async def check_ready(self) -> None:
        return None


class QueryFailingEmbedder(HashEmbedder):
    """Embeds documents like `HashEmbedder` but fails every query, as during an outage."""

    async def embed_query(self, text: str) -> list[float]:
        raise EmbedderUnavailable()

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbedderUnavailable()


class SlowEmbedder(HashEmbedder):
    """Embeds like `HashEmbedder`, but documents only after a delay."""

    def __init__(self, *, delay_seconds: float) -> None:
        super().__init__()
        self._delay_seconds: float = delay_seconds

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        await asyncio.sleep(self._delay_seconds)
        return await super().embed_documents(texts)


class QuoteFailingEmbedder(HashEmbedder):
    """Embeds like `HashEmbedder` but fails batched queries, which only quote selection makes."""

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbedderUnavailable()


class CountingEmbedder(HashEmbedder):
    """Embeds like `HashEmbedder` and counts batched query and document calls."""

    def __init__(self) -> None:
        super().__init__()
        self.query_batches: int = 0
        self.document_batches: int = 0

    def reset(self) -> None:
        self.query_batches = 0
        self.document_batches = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_batches += 1
        return await super().embed_documents(texts)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.query_batches += 1
        return await super().embed_queries(texts)


class DocumentControlledEmbedder(HashEmbedder):
    """Embeds like `HashEmbedder` until told to fail or block document embedding.

    Set the controls after ingestion, so only quote selection's passage embedding is affected.
    """

    def __init__(self) -> None:
        super().__init__()
        self.fail_documents: bool = False
        self.block_documents: bool = False
        self.blocked: asyncio.Event = asyncio.Event()
        self.cancelled: bool = False

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail_documents:
            raise EmbedderUnavailable()
        if self.block_documents:
            self.blocked.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return await super().embed_documents(texts)
