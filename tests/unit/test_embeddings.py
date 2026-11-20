import math
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic_settings import SettingsConfigDict
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from sourcehaven.config import Settings
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.hashing import HashEmbedder, WhitespaceTokenCounter
from sourcehaven.embeddings.protocol import EmbedderNotReady, EmbedderUnavailable
from sourcehaven.embeddings.tei import HfTokenCounter, TeiEmbedder
from tests.support.embeddings import (
    TeiRequest,
    cosine,
    make_config,
    tei_mock,
    tei_with_info,
    tei_with_response,
)


class EnvironmentOnlySettings(Settings):
    """Settings that ignore any local `.env` file."""

    model_config = SettingsConfigDict(env_file=None)


def test_fingerprint_changes_with_any_field() -> None:
    base: EmbeddingConfig = make_config()
    assert base.fingerprint() == make_config().fingerprint()
    assert base.fingerprint() != replace(base, query_prefix="").fingerprint()
    assert base.fingerprint() != replace(base, model_revision="other").fingerprint()


def test_from_settings_for_tei_copies_the_configured_values() -> None:
    settings: Settings = EnvironmentOnlySettings(
        embedding_provider="tei",
        embedding_model_id="test/model",
        embedding_model_revision="rev-1",
        embedding_dimensions=768,
    )
    config: EmbeddingConfig = EmbeddingConfig.from_settings(settings)
    assert config.provider == "tei"
    assert config.model_id == "test/model"
    assert config.model_revision == "rev-1"
    assert config.normalize is True
    assert config.distance == "cosine"
    assert config.max_input_tokens == settings.embedding_max_input_tokens
    assert config.chunk_tokens == settings.chunk_tokens
    assert config.chunk_overlap == settings.chunk_overlap


def test_from_settings_for_hash_uses_fixed_values() -> None:
    settings: Settings = EnvironmentOnlySettings(embedding_provider="hash")
    config: EmbeddingConfig = EmbeddingConfig.from_settings(settings)
    assert (config.model_id, config.model_revision, config.dimensions) == ("hash-bow", "1", 256)
    assert (config.query_prefix, config.document_prefix) == ("", "")


async def test_hash_embedder_is_deterministic_and_normalised() -> None:
    embedder: HashEmbedder = HashEmbedder(dimensions=256)
    first: list[float] = (await embedder.embed_documents(["Alpha beta beta"]))[0]
    again: list[float] = (await embedder.embed_documents(["Alpha beta beta"]))[0]
    assert first == again and len(first) == 256
    assert math.isclose(math.fsum(v * v for v in first), 1.0)


async def test_hash_embedder_ranks_shared_words_higher() -> None:
    embedder: HashEmbedder = HashEmbedder()
    query: list[float] = await embedder.embed_query("warranty period months")
    near, far = await embedder.embed_documents(
        ["The warranty period is 24 months.", "Shipping is free in Prague."]
    )
    assert cosine(query, near) > cosine(query, far)


async def test_hash_embedder_keeps_text_without_tokens_as_zero_vector() -> None:
    vector: list[float] = await HashEmbedder(dimensions=8).embed_query("  ... ")
    assert vector == [0.0] * 8


async def test_hash_embedder_config_matches_settings_defaults() -> None:
    embedder: HashEmbedder = HashEmbedder()
    assert embedder.config.dimensions == 256
    assert embedder.config.provider == "hash"
    await embedder.check_ready()


def test_whitespace_token_counter_counts_words() -> None:
    assert WhitespaceTokenCounter().count("one  two\nthree") == 3


async def test_tei_embedder_batches_and_prefixes() -> None:
    seen: list[TeiRequest] = []
    transport: httpx.MockTransport = tei_mock(seen, dimensions=3)
    embedder: TeiEmbedder = TeiEmbedder(
        httpx.AsyncClient(transport=transport, base_url="http://tei"),
        make_config(dimensions=3),
        batch_size=2,
    )
    vectors: list[list[float]] = await embedder.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3 and [len(r["inputs"]) for r in seen] == [2, 1]
    assert all(r["normalize"] is True and r["truncate"] is False for r in seen)
    await embedder.embed_query("q")
    assert seen[-1]["inputs"] == ["query: q"]


async def test_tei_embedder_batches_queries_with_the_query_prefix() -> None:
    seen: list[TeiRequest] = []
    embedder: TeiEmbedder = TeiEmbedder(
        httpx.AsyncClient(transport=tei_mock(seen, dimensions=3), base_url="http://tei"),
        make_config(dimensions=3),
        batch_size=2,
    )
    vectors: list[list[float]] = await embedder.embed_queries(["a", "b", "c"])
    assert len(vectors) == 3
    assert [r["inputs"] for r in seen] == [["query: a", "query: b"], ["query: c"]]
    assert await embedder.embed_queries([]) == [] and len(seen) == 2


async def test_hash_embedder_embeds_queries_like_single_queries() -> None:
    embedder: HashEmbedder = HashEmbedder()
    assert await embedder.embed_queries(["warranty period", "support"]) == [
        await embedder.embed_query("warranty period"),
        await embedder.embed_query("support"),
    ]


async def test_tei_embedder_returns_nothing_for_no_documents() -> None:
    seen: list[TeiRequest] = []
    transport: httpx.MockTransport = tei_mock(seen, dimensions=3)
    embedder: TeiEmbedder = TeiEmbedder(
        httpx.AsyncClient(transport=transport, base_url="http://tei"), make_config(dimensions=3)
    )
    assert await embedder.embed_documents([]) == []
    assert seen == []


async def test_tei_embedder_rejects_wrong_dimensions() -> None:
    embedder: TeiEmbedder = tei_with_response(httpx.Response(200, json=[[0.1, 0.2]]))
    with pytest.raises(EmbedderUnavailable, match="dimensions"):
        await embedder.embed_query("q")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="loading"),
        httpx.Response(500, text="boom"),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
    ids=["503", "500", "connect-error", "timeout"],
)
async def test_tei_embedder_maps_transport_failures_to_unavailable(
    response: httpx.Response | Exception,
) -> None:
    embedder: TeiEmbedder = tei_with_response(response)
    with pytest.raises(EmbedderUnavailable):
        await embedder.embed_documents(["a"])


async def test_tei_check_ready_accepts_matching_model() -> None:
    await tei_with_info({}).check_ready()


async def test_tei_check_ready_rejects_model_mismatch() -> None:
    embedder: TeiEmbedder = tei_with_info({"model_id": "other/model"})
    with pytest.raises(EmbedderNotReady, match="model"):
        await embedder.check_ready()


async def test_tei_check_ready_rejects_revision_mismatch() -> None:
    embedder: TeiEmbedder = tei_with_info({"model_sha": "other-sha"})
    with pytest.raises(EmbedderNotReady, match="revision"):
        await embedder.check_ready()


async def test_tei_check_ready_reports_unreachable_service() -> None:
    embedder: TeiEmbedder = tei_with_response(httpx.ConnectError("refused"))
    with pytest.raises(EmbedderNotReady, match="unreachable"):
        await embedder.check_ready()


def test_hf_token_counter_counts_ids_without_special_tokens(tmp_path: Path) -> None:
    vocabulary: dict[str, int] = {"[UNK]": 0, "hello": 1, "world": 2}
    tokenizer: Tokenizer = Tokenizer(WordLevel(vocabulary, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer_file: Path = tmp_path / "tokenizer.json"
    tokenizer.save(str(tokenizer_file))
    counter: HfTokenCounter = HfTokenCounter(tokenizer_file)
    assert counter.count("hello world hello") == 3
    assert counter.count("") == 0
