from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from evals.embedding import CachedEmbedder, VectorCache, benchmark_config, ensure_tokenizer
from sourcehaven.config import Settings
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.hashing import HashEmbedder
from sourcehaven.embeddings.protocol import Embedder, EmbedderNotReady


class _RecordingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.document_calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []
        self.ready_calls: int = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return await super().embed_documents(texts)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.query_calls.append(list(texts))
        return await super().embed_queries(texts)

    async def check_ready(self) -> None:
        self.ready_calls += 1
        raise EmbedderNotReady("down")


def test_cached_embedder_satisfies_the_embedder_protocol(tmp_path: Path) -> None:
    embedder: Embedder = CachedEmbedder(HashEmbedder(), VectorCache(tmp_path / "v.sqlite3"))
    assert embedder.config.provider == "hash"


async def test_cached_embedder_embeds_each_text_once(tmp_path: Path) -> None:
    embedder: CachedEmbedder = CachedEmbedder(HashEmbedder(), VectorCache(tmp_path / "v.sqlite3"))
    first: list[list[float]] = await embedder.embed_documents(["a", "b"])
    second: list[list[float]] = await embedder.embed_documents(["b", "a", "c"])
    assert second[:2] == [first[1], first[0]]
    assert embedder.embedded_texts == 3
    assert embedder.embed_seconds >= 0.0


async def test_misses_go_to_inner_as_one_ordered_deduplicated_batch(tmp_path: Path) -> None:
    inner: _RecordingEmbedder = _RecordingEmbedder()
    embedder: CachedEmbedder = CachedEmbedder(inner, VectorCache(tmp_path / "v.sqlite3"))
    await embedder.embed_documents(["b"])
    vectors: list[list[float]] = await embedder.embed_documents(["c", "b", "a", "c"])
    assert inner.document_calls == [["b"], ["c", "a"]]
    assert vectors[0] == vectors[3]
    assert embedder.embedded_texts == 3


async def test_fully_cached_call_does_not_reach_inner(tmp_path: Path) -> None:
    inner: _RecordingEmbedder = _RecordingEmbedder()
    embedder: CachedEmbedder = CachedEmbedder(inner, VectorCache(tmp_path / "v.sqlite3"))
    await embedder.embed_queries(["q"])
    await embedder.embed_queries(["q"])
    assert inner.query_calls == [["q"]]
    assert await embedder.embed_documents([]) == []


async def test_query_and_document_vectors_are_cached_separately(tmp_path: Path) -> None:
    inner: _RecordingEmbedder = _RecordingEmbedder()
    embedder: CachedEmbedder = CachedEmbedder(inner, VectorCache(tmp_path / "v.sqlite3"))
    await embedder.embed_documents(["same"])
    await embedder.embed_queries(["same"])
    assert inner.document_calls == [["same"]]
    assert inner.query_calls == [["same"]]
    assert embedder.embedded_texts == 2


async def test_embed_query_shares_the_query_cache(tmp_path: Path) -> None:
    inner: _RecordingEmbedder = _RecordingEmbedder()
    embedder: CachedEmbedder = CachedEmbedder(inner, VectorCache(tmp_path / "v.sqlite3"))
    single: list[float] = await embedder.embed_query("q")
    batch: list[list[float]] = await embedder.embed_queries(["q"])
    assert batch == [single]
    assert inner.query_calls == [["q"]]


async def test_cache_survives_reopening(tmp_path: Path) -> None:
    path: Path = tmp_path / "v.sqlite3"
    first_cache: VectorCache = VectorCache(path)
    first: CachedEmbedder = CachedEmbedder(HashEmbedder(), first_cache)
    expected: list[list[float]] = await first.embed_documents(["persisted"])
    first_cache.close()

    second: CachedEmbedder = CachedEmbedder(HashEmbedder(), VectorCache(path))
    assert await second.embed_documents(["persisted"]) == expected
    assert second.embedded_texts == 0


async def test_different_configurations_do_not_share_vectors(tmp_path: Path) -> None:
    cache: VectorCache = VectorCache(tmp_path / "v.sqlite3")
    default: CachedEmbedder = CachedEmbedder(HashEmbedder(), cache)
    other: CachedEmbedder = CachedEmbedder(HashEmbedder(dimensions=8, config=None), cache)
    await default.embed_documents(["x"])
    assert len((await other.embed_documents(["x"]))[0]) == 8
    assert other.embedded_texts == 1


async def test_check_ready_and_config_delegate(tmp_path: Path) -> None:
    inner: _RecordingEmbedder = _RecordingEmbedder()
    embedder: CachedEmbedder = CachedEmbedder(inner, VectorCache(tmp_path / "v.sqlite3"))
    assert embedder.config == inner.config
    with pytest.raises(EmbedderNotReady):
        await embedder.check_ready()
    assert inner.ready_calls == 1


def test_vector_cache_roundtrips_floats_exactly(tmp_path: Path) -> None:
    cache: VectorCache = VectorCache(tmp_path / "v.sqlite3")
    assert cache.get("k") is None
    cache.put_many({"k": [0.1, -2.5, 1e-300]})
    assert cache.get("k") == [0.1, -2.5, 1e-300]
    cache.put_many({"k": [1.0]})
    assert cache.get("k") == [1.0]


def test_benchmark_config_overrides_passage_size_and_requires_tei() -> None:
    settings: Settings = Settings(embedding_model_revision="abc")
    config: EmbeddingConfig = benchmark_config(settings, chunk_tokens=150, chunk_overlap=20)
    assert (config.chunk_tokens, config.chunk_overlap, config.model_revision) == (150, 20, "abc")
    with pytest.raises(ValueError):
        benchmark_config(Settings(embedding_provider="hash"), chunk_tokens=400, chunk_overlap=60)


@pytest.mark.parametrize(
    ("chunk_tokens", "chunk_overlap"), [(0, 0), (-5, 0), (100, -1), (100, 100), (100, 150)]
)
def test_benchmark_config_rejects_an_unusable_passage_size(
    chunk_tokens: int, chunk_overlap: int
) -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        benchmark_config(
            Settings(embedding_model_revision="abc"),
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
        )


async def test_tokenizer_is_downloaded_once(tmp_path: Path) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=b'{"model": {}}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path: Path = await ensure_tokenizer("org/model", "rev1", tmp_path, client)
        again: Path = await ensure_tokenizer("org/model", "rev1", tmp_path, client)

    assert requested == ["https://huggingface.co/org/model/resolve/rev1/tokenizer.json"]
    assert path == again == tmp_path / "tokenizers" / "org--model" / "rev1" / "tokenizer.json"
    assert path.read_bytes() == b'{"model": {}}'


async def test_tokenizer_failure_leaves_no_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await ensure_tokenizer("org/model", "rev1", tmp_path, client)

    assert not [path for path in (tmp_path / "tokenizers").rglob("*") if path.is_file()]
