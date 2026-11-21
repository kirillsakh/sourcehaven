import hashlib
import os
import sqlite3
import tempfile
import time
from array import array
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import httpx

from sourcehaven.config import Settings
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.protocol import Embedder

_TOKENIZER_URL: str = "https://huggingface.co/{model_id}/resolve/{revision}/tokenizer.json"


def benchmark_config(
    settings: Settings, *, chunk_tokens: int, chunk_overlap: int
) -> EmbeddingConfig:
    """Build the embedding configuration for a run, overriding the passage size.

    Raises:
        ValueError: If the settings do not select the `tei` provider.
    """
    if settings.embedding_provider != "tei":
        raise ValueError("The benchmark needs embedding_provider=tei")
    return replace(
        EmbeddingConfig.from_settings(settings),
        chunk_tokens=chunk_tokens,
        chunk_overlap=chunk_overlap,
    )


async def ensure_tokenizer(
    model_id: str, revision: str, cache_dir: Path, client: httpx.AsyncClient
) -> Path:
    """Return the model's `tokenizer.json` at `revision`, downloading it on first use.

    Raises:
        httpx.HTTPStatusError: If the Hub answers with a non-2xx status. No file is left behind.
    """
    target: Path = (
        cache_dir / "tokenizers" / model_id.replace("/", "--") / revision / "tokenizer.json"
    )
    if target.exists():
        return target
    response: httpx.Response = await client.get(
        _TOKENIZER_URL.format(model_id=model_id, revision=revision), follow_redirects=True
    )
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory temp file so the rename is atomic and a failed write leaves no tokenizer.json.
    descriptor: int
    temporary_name: str
    descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(response.content)
        Path(temporary_name).replace(target)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return target


class VectorCache:
    """SQLite-backed store of embedding vectors keyed by an opaque string."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection = sqlite3.connect(path)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)"
        )
        self._connection.commit()

    def get(self, key: str) -> list[float] | None:
        row: tuple[bytes] | None = self._connection.execute(
            "SELECT vector FROM vectors WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        values: array[float] = array("d")
        values.frombytes(row[0])
        return values.tolist()

    def put_many(self, items: Mapping[str, Sequence[float]]) -> None:
        self._connection.executemany(
            "INSERT OR REPLACE INTO vectors (key, vector) VALUES (?, ?)",
            [(key, array("d", vector).tobytes()) for key, vector in items.items()],
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


class CachedEmbedder:
    """Embedder wrapper that serves repeated texts from a `VectorCache`.

    `embedded_texts` and `embed_seconds` are cumulative and count only the texts sent to the
    wrapped embedder and the time spent in those calls; callers measure a delta around a call.
    """

    def __init__(self, inner: Embedder, cache: VectorCache) -> None:
        self._inner: Embedder = inner
        self._cache: VectorCache = cache
        self.embedded_texts: int = 0
        self.embed_seconds: float = 0.0

    @property
    def config(self) -> EmbeddingConfig:
        return self._inner.config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed("document", texts, self._inner.embed_documents)

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_queries([text]))[0]

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed("query", texts, self._inner.embed_queries)

    async def check_ready(self) -> None:
        await self._inner.check_ready()

    async def _embed(
        self,
        kind: str,
        texts: Sequence[str],
        embed_missing: Callable[[Sequence[str]], Awaitable[list[list[float]]]],
    ) -> list[list[float]]:
        fingerprint: str = self.config.fingerprint()
        keys: list[str] = [
            f"{fingerprint}:{kind}:{hashlib.sha256(text.encode()).hexdigest()}" for text in texts
        ]
        found: dict[str, list[float]] = {}
        missing: dict[str, str] = {}
        for key, text in zip(keys, texts, strict=True):
            if key in found or key in missing:
                continue
            cached: list[float] | None = self._cache.get(key)
            if cached is None:
                missing[key] = text
            else:
                found[key] = cached
        if missing:
            started: float = time.perf_counter()
            vectors: list[list[float]] = await embed_missing(list(missing.values()))
            self.embed_seconds += time.perf_counter() - started
            self.embedded_texts += len(missing)
            computed: dict[str, list[float]] = dict(zip(missing, vectors, strict=True))
            self._cache.put_many(computed)
            found.update(computed)
        return [found[key] for key in keys]
