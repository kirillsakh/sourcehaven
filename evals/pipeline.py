import math
import statistics
import time
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from evals.corpus import CorpusDocument, Manifest, document_path, extract_document
from evals.embedding import CachedEmbedder
from evals.normalize import normalize, word_coverage
from evals.questions import GoldSpan, Question
from evals.scoring import (
    Passage,
    QuestionOutcome,
    Ranked,
    SpanLocation,
    SpanOutcome,
    choose_passages,
    contains,
    covering_rank,
    locate_span,
)
from sourcehaven.domain.models import ChunkDraft, Citation, Evidence, ExtractedSource
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.protocol import Embedder, TokenCounter
from sourcehaven.generation.prompts import LabelledEvidence
from sourcehaven.ingestion.chunking import chunk_pages
from sourcehaven.ingestion.pdf import SourceAdapter
from sourcehaven.qa.quotes import PassageSentences, embed_passage_sentences, select_quotes
from sourcehaven.retrieval.search import CANDIDATE_LIMIT

QUOTE_TIMEOUT_SECONDS: Final[float] = 60.0

_ANSWERED_KINDS: Final[frozenset[str]] = frozenset({"answerable", "conflict"})
_QUOTE_LABEL: Final[str] = "S1"
_P50_INDEX: Final[int] = 49
_P95_INDEX: Final[int] = 94
_MILLISECONDS: Final[float] = 1000.0


@dataclass(frozen=True)
class DocumentPassages:
    """One corpus document's benchmarked excerpt and the passages cut from it."""

    document: CorpusDocument
    source: ExtractedSource
    passages: tuple[Passage, ...]
    extract_seconds: float


@dataclass(frozen=True)
class SpeedFigures:
    """Informative speed figures of one run, measured on the development host.

    Attributes:
        embedded_passages: Passages sent to the embedder (not served from the vector cache).
        passages_per_second: Embedding rate of those passages; None when none were embedded.
        query_p50_ms: Median query-embedding latency; None without a latency embedder.
        query_p95_ms: 95th percentile of the same; equals the median for a single sample.
    """

    extract_seconds_per_page: float
    passages_per_page: float
    embedded_passages: int
    passages_per_second: float | None
    query_p50_ms: float | None
    query_p95_ms: float | None


@dataclass(frozen=True)
class BenchmarkResult:
    outcomes: tuple[QuestionOutcome, ...]
    documents: tuple[DocumentPassages, ...]
    speed: SpeedFigures
    config: EmbeddingConfig


@dataclass(frozen=True)
class _Vectored:
    passage: Passage
    vector: Sequence[float]
    norm: float


def build_passages(
    document: CorpusDocument,
    path: Path,
    adapter: SourceAdapter,
    counter: TokenCounter,
    *,
    chunk_tokens: int,
    chunk_overlap: int,
    max_pages: int,
) -> DocumentPassages:
    """Extract a document's benchmark excerpt and split it into passages.

    Raises:
        IngestionError: If the adapter cannot parse the file.
    """
    started: float = time.perf_counter()
    source: ExtractedSource = extract_document(document, path, adapter, max_pages=max_pages)
    extract_seconds: float = time.perf_counter() - started
    drafts: list[ChunkDraft] = chunk_pages(
        source.pages, counter, chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap
    )
    passages: tuple[Passage, ...] = tuple(
        Passage(
            document=document.id,
            ordinal=draft.ordinal,
            text=draft.text,
            normalized=normalize(draft.text),
            pages=draft.span,
        )
        for draft in drafts
    )
    return DocumentPassages(
        document=document, source=source, passages=passages, extract_seconds=extract_seconds
    )


async def run_benchmark(
    manifest: Manifest,
    questions: Sequence[Question],
    files_dir: Path,
    *,
    adapter: SourceAdapter,
    counter: TokenCounter,
    embedder: CachedEmbedder,
    latency_embedder: Embedder | None,
    chunk_tokens: int,
    chunk_overlap: int,
    max_pages: int,
) -> BenchmarkResult:
    """Run the retrieval benchmark: split, embed, rank, select and quote.

    Every manifest document is extracted and split, all passages are embedded in one call and
    all questions in another. Each question then ranks the passages of its own documents.

    Args:
        manifest: The corpus.
        questions: The questions to score.
        files_dir: Directory holding each document's verified PDF.
        adapter: Parser for the PDFs.
        counter: Token counter of the embedding model's tokenizer.
        embedder: Embedder with a vector cache; its counters give the passage-embedding speed.
        latency_embedder: Uncached embedder used to time one query at a time, or None to skip.
        chunk_tokens: Maximum tokens per passage.
        chunk_overlap: Tokens shared by consecutive passages.
        max_pages: Page limit passed to the adapter.

    Returns:
        Per-question outcomes in question order, the split documents, speed figures and the
        embedder's configuration.

    Raises:
        IngestionError: If a document cannot be parsed.
        ValueError: If an answered question has no reference answer.
    """
    documents: tuple[DocumentPassages, ...] = tuple(
        build_passages(
            document,
            document_path(files_dir, document),
            adapter,
            counter,
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
            max_pages=max_pages,
        )
        for document in manifest.documents
    )
    passages: list[Passage] = [p for item in documents for p in item.passages]
    texts_before: int = embedder.embedded_texts
    seconds_before: float = embedder.embed_seconds
    passage_vectors: list[list[float]] = await embedder.embed_documents([p.text for p in passages])
    embedded: int = embedder.embedded_texts - texts_before
    embed_seconds: float = embedder.embed_seconds - seconds_before
    query_vectors: list[list[float]] = await embedder.embed_queries([q.text for q in questions])

    vectored: list[_Vectored] = [
        _Vectored(passage, vector, _norm(vector))
        for passage, vector in zip(passages, passage_vectors, strict=True)
    ]
    by_document: dict[str, list[_Vectored]] = {item.document.id: [] for item in documents}
    for entry in vectored:
        by_document[entry.passage.document].append(entry)
    pages_by_document: dict[str, ExtractedSource] = {
        item.document.id: item.source for item in documents
    }

    outcomes: list[QuestionOutcome] = []
    for question, query_vector in zip(questions, query_vectors, strict=True):
        outcomes.append(
            await _score_question(question, query_vector, by_document, pages_by_document, embedder)
        )
    latencies: list[float] = await _query_latencies(latency_embedder, questions)
    speed: SpeedFigures = _speed(documents, embedded, embed_seconds, latencies)
    return BenchmarkResult(
        outcomes=tuple(outcomes), documents=documents, speed=speed, config=embedder.config
    )


async def _score_question(
    question: Question,
    query_vector: Sequence[float],
    by_document: Mapping[str, Sequence[_Vectored]],
    sources: Mapping[str, ExtractedSource],
    embedder: CachedEmbedder,
) -> QuestionOutcome:
    ranking: list[Ranked] = _rank(question, query_vector, by_document)
    candidates: list[Ranked] = ranking[:CANDIDATE_LIMIT]
    chosen: list[Ranked] = choose_passages(candidates, threshold=0.0)
    spans: list[SpanOutcome] = [
        await _score_span(
            question, span, query_vector, ranking, chosen, by_document, sources, embedder
        )
        for span in question.gold
    ]
    chosen_passages: list[Passage] = [ranked.passage for ranked in chosen]
    return QuestionOutcome(
        question=question,
        top_similarity=ranking[0].similarity if ranking else None,
        covering_rank=covering_rank([r.passage for r in ranking], question.gold),
        hit=bool(question.gold)
        and all(any(contains(p, span) for p in chosen_passages) for span in question.gold),
        spans=tuple(spans),
        candidates=tuple(candidates),
    )


def _rank(
    question: Question,
    query_vector: Sequence[float],
    by_document: Mapping[str, Sequence[_Vectored]],
) -> list[Ranked]:
    query_norm: float = _norm(query_vector)
    ranking: list[Ranked] = [
        Ranked(entry.passage, _cosine(entry.vector, entry.norm, query_vector, query_norm))
        for document_id in question.documents
        for entry in by_document[document_id]
    ]
    ranking.sort(key=lambda r: (-r.similarity, r.passage.document, r.passage.ordinal))
    return ranking


async def _score_span(
    question: Question,
    span: GoldSpan,
    query_vector: Sequence[float],
    ranking: Sequence[Ranked],
    chosen: Sequence[Ranked],
    by_document: Mapping[str, Sequence[_Vectored]],
    sources: Mapping[str, ExtractedSource],
    embedder: CachedEmbedder,
) -> SpanOutcome:
    location: SpanLocation = locate_span(span, sources[span.document].pages)
    in_document: bool = any(contains(e.passage, span) for e in by_document[span.document])
    best_rank: int | None = next(
        (rank for rank, r in enumerate(ranking, start=1) if contains(r.passage, span)), None
    )
    first_chosen: Ranked | None = next((r for r in chosen if contains(r.passage, span)), None)
    quote: str | None = None
    coverage: float | None = None
    if first_chosen is not None and question.kind in _ANSWERED_KINDS:
        quote = await _select_quote(question, first_chosen, query_vector, embedder)
        coverage = word_coverage(span.text, quote)
    return SpanOutcome(
        span=span,
        location=location,
        split=location != "missing" and not in_document,
        best_rank=best_rank,
        selected=first_chosen is not None,
        page_correct=(
            None
            if first_chosen is None
            else first_chosen.passage.pages.start <= span.page <= first_chosen.passage.pages.end
        ),
        quote=quote,
        quote_coverage=coverage,
    )


async def _select_quote(
    question: Question, ranked: Ranked, query_vector: Sequence[float], embedder: CachedEmbedder
) -> str:
    if question.reference_answer is None:
        raise ValueError(f"Question {question.id} has no reference answer")
    evidence: Evidence = ranked.passage.evidence(ranked.similarity)
    sentences: Awaitable[Mapping[str, PassageSentences]] = embed_passage_sentences(
        [LabelledEvidence(_QUOTE_LABEL, evidence)], embedder
    )
    selected: list[Citation] = await select_quotes(
        f"{question.reference_answer} [{_QUOTE_LABEL}]",
        [Citation(_QUOTE_LABEL, evidence, cited=True, quote="")],
        passage_sentences=sentences,
        question_vector=query_vector,
        embedder=embedder,
        timeout_seconds=QUOTE_TIMEOUT_SECONDS,
    )
    return selected[0].quote


async def _query_latencies(embedder: Embedder | None, questions: Sequence[Question]) -> list[float]:
    if embedder is None:
        return []
    samples: list[float] = []
    for question in questions:
        started: float = time.perf_counter()
        await embedder.embed_query(question.text)
        samples.append((time.perf_counter() - started) * _MILLISECONDS)
    return samples


def _speed(
    documents: Sequence[DocumentPassages],
    embedded: int,
    embed_seconds: float,
    latencies: Sequence[float],
) -> SpeedFigures:
    pages: int = sum(len(item.source.pages) for item in documents)
    passages: int = sum(len(item.passages) for item in documents)
    extract_seconds: float = sum(item.extract_seconds for item in documents)
    p50: float | None = None
    p95: float | None = None
    if len(latencies) == 1:
        p50 = p95 = latencies[0]
    elif latencies:
        cuts: list[float] = statistics.quantiles(latencies, n=100, method="inclusive")
        p50, p95 = cuts[_P50_INDEX], cuts[_P95_INDEX]
    return SpeedFigures(
        extract_seconds_per_page=extract_seconds / pages if pages else 0.0,
        passages_per_page=passages / pages if pages else 0.0,
        embedded_passages=embedded,
        passages_per_second=embedded / embed_seconds if embedded and embed_seconds > 0 else None,
        query_p50_ms=p50,
        query_p95_ms=p95,
    )


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in vector))


def _cosine(
    left: Sequence[float], left_norm: float, right: Sequence[float], right_norm: float
) -> float:
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    dot: float = math.fsum(a * b for a, b in zip(left, right, strict=True))
    return dot / (left_norm * right_norm)
