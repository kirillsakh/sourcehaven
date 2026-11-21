import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from evals.corpus import CorpusDocument, Manifest
from evals.embedding import CachedEmbedder, VectorCache
from evals.pipeline import BenchmarkResult, DocumentPassages, build_passages, run_benchmark
from evals.questions import GoldSpan, Question, QuestionKind
from evals.scoring import Metrics, QuestionOutcome, summarize
from sourcehaven.domain.models import PageSpan
from sourcehaven.embeddings.hashing import HashEmbedder, WhitespaceTokenCounter
from sourcehaven.ingestion.pdf import PdfAdapter
from sourcehaven.retrieval.search import CANDIDATE_LIMIT
from tests.support.fixtures import fixture

_CHUNK_TOKENS: int = 20
_WARRANTY: str = "The Sourcehaven warranty period is 24 months."
_BRIDGE: str = "The bridge was completed in 1931."


def corpus_document(
    document_id: str, files_dir: Path, *, page_range: PageSpan | None = None
) -> CorpusDocument:
    path: Path = files_dir / f"{document_id}.pdf"
    return CorpusDocument(
        id=document_id,
        title=document_id,
        author="Test",
        url=f"https://example.test/{document_id}.pdf",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
        page_count=6,
        licence="Test",
        licence_url="https://example.test/licence",
        layout="plain",
        page_range=page_range,
        selected_by_default=True,
    )


def make_question(
    question_id: str,
    kind: QuestionKind,
    text: str,
    documents: tuple[str, ...],
    *gold: GoldSpan,
) -> Question:
    return Question(
        id=question_id,
        kind=kind,
        text=text,
        documents=documents,
        reference_answer=None if kind == "unanswerable" else f"{gold[0].text}",
        gold=gold,
    )


@pytest.fixture
def files_dir(tmp_path: Path) -> Path:
    directory: Path = tmp_path / "files"
    directory.mkdir()
    shutil.copy(fixture("facts_small_en.pdf"), directory / "facts.pdf")
    shutil.copy(fixture("multipage_en.pdf"), directory / "multipage.pdf")
    return directory


@pytest.fixture
def manifest(files_dir: Path) -> Manifest:
    return Manifest(
        version=1,
        documents=(corpus_document("facts", files_dir), corpus_document("multipage", files_dir)),
    )


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[VectorCache]:
    vectors: VectorCache = VectorCache(tmp_path / "cache" / "vectors.sqlite3")
    yield vectors
    vectors.close()


@pytest.fixture
def questions() -> tuple[Question, ...]:
    return (
        make_question(
            "warranty",
            "answerable",
            "How long is the warranty period?",
            ("facts",),
            GoldSpan(document="facts", page=1, text=_WARRANTY),
        ),
        make_question(
            "bridge",
            "answerable",
            "When was the bridge completed?",
            ("multipage",),
            GoldSpan(document="multipage", page=4, text=_BRIDGE),
        ),
        make_question(
            "peru", "unanswerable", "What is the capital of Peru?", ("facts", "multipage")
        ),
    )


async def run(
    manifest: Manifest,
    questions: tuple[Question, ...],
    files_dir: Path,
    cache: VectorCache,
    *,
    chunk_tokens: int = _CHUNK_TOKENS,
    latency_embedder: HashEmbedder | None = None,
) -> BenchmarkResult:
    return await run_benchmark(
        manifest,
        questions,
        files_dir,
        adapter=PdfAdapter(),
        counter=WhitespaceTokenCounter(),
        embedder=CachedEmbedder(HashEmbedder(), cache),
        latency_embedder=latency_embedder,
        chunk_tokens=chunk_tokens,
        chunk_overlap=0,
        max_pages=100,
    )


def outcome(result: BenchmarkResult, question_id: str) -> QuestionOutcome:
    return next(o for o in result.outcomes if o.question.id == question_id)


async def test_end_to_end_on_the_synthetic_fixtures(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    result: BenchmarkResult = await run(manifest, questions, files_dir, cache)

    warranty: QuestionOutcome = outcome(result, "warranty")
    assert warranty.hit
    assert warranty.covering_rank == 1
    (span,) = warranty.spans
    assert span.location == "on_page"
    assert span.page_correct
    assert span.quote_coverage is not None
    assert span.quote_coverage >= 0.8
    bridge: QuestionOutcome = outcome(result, "bridge")
    assert bridge.spans[0].selected
    assert bridge.spans[0].page_correct
    peru: QuestionOutcome = outcome(result, "peru")
    assert not peru.hit
    assert peru.covering_rank is None
    assert peru.spans == ()
    assert peru.top_similarity is not None
    assert result.config == HashEmbedder().config
    assert [d.document.id for d in result.documents] == ["facts", "multipage"]


async def test_summary_recall_matches_the_hits(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    result: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    metrics: Metrics = summarize(result.outcomes)
    assert metrics.recall_at_8 == metrics.thresholds[0].recall_at_8 == 1.0
    assert metrics.extraction_coverage == 1.0
    assert metrics.split_spans == 0


async def test_candidates_are_the_ranked_top_with_stable_ties(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    result: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    for item in result.outcomes:
        keys: list[tuple[float, str, int]] = [
            (-c.similarity, c.passage.document, c.passage.ordinal) for c in item.candidates
        ]
        assert keys == sorted(keys)
        assert len(item.candidates) <= CANDIDATE_LIMIT
        assert item.top_similarity == item.candidates[0].similarity


async def test_excerpt_passages_keep_physical_pages(manifest: Manifest, files_dir: Path) -> None:
    excerpt: CorpusDocument = corpus_document(
        "multipage", files_dir, page_range=PageSpan(start=3, end=5)
    )
    pages: DocumentPassages = build_passages(
        excerpt,
        files_dir / "multipage.pdf",
        PdfAdapter(),
        WhitespaceTokenCounter(),
        chunk_tokens=_CHUNK_TOKENS,
        chunk_overlap=0,
        max_pages=100,
    )
    assert pages.passages
    assert all(3 <= p.pages.start <= p.pages.end <= 5 for p in pages.passages)
    assert [p.ordinal for p in pages.passages] == list(range(len(pages.passages)))
    assert {p.document for p in pages.passages} == {"multipage"}
    assert [page.page for page in pages.source.pages] == [3, 4, 5]
    assert pages.extract_seconds >= 0.0


async def test_second_run_embeds_nothing(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    first: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    second: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    passages: list[str] = [p.text for d in first.documents for p in d.passages]
    assert first.speed.embedded_passages == len(set(passages))
    assert first.speed.passages_per_second is not None
    assert first.speed.passages_per_second > 0
    assert second.speed.embedded_passages == 0
    assert second.speed.passages_per_second is None
    pages: int = sum(len(d.source.pages) for d in first.documents)
    assert first.speed.passages_per_page == len(passages) / pages
    assert first.speed.extract_seconds_per_page >= 0.0


async def test_a_question_only_sees_its_selected_documents(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    result: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    bridge: QuestionOutcome = outcome(result, "bridge")
    assert bridge.candidates
    assert {c.passage.document for c in bridge.candidates} == {"multipage"}
    peru: QuestionOutcome = outcome(result, "peru")
    assert {c.passage.document for c in peru.candidates} == {"facts", "multipage"}


async def test_split_and_missing_spans_are_told_apart(
    manifest: Manifest, files_dir: Path, cache: VectorCache
) -> None:
    probes: tuple[Question, ...] = (
        make_question(
            "split",
            "answerable",
            "How long is the warranty period?",
            ("facts",),
            GoldSpan(document="facts", page=1, text=_WARRANTY),
        ),
        make_question(
            "missing",
            "answerable",
            "How long is the warranty period?",
            ("facts",),
            GoldSpan(document="facts", page=1, text="A sentence that is not in the file."),
        ),
    )
    result: BenchmarkResult = await run(manifest, probes, files_dir, cache, chunk_tokens=5)

    (split,) = outcome(result, "split").spans
    assert (split.location, split.split, split.best_rank) == ("on_page", True, None)
    assert not split.selected
    assert split.page_correct is None
    assert split.quote is None
    assert split.quote_coverage is None
    assert not outcome(result, "split").hit
    (missing,) = outcome(result, "missing").spans
    assert (missing.location, missing.split, missing.best_rank) == ("missing", False, None)
    assert outcome(result, "missing").covering_rank is None


async def test_latency_percentiles_need_a_latency_embedder(
    manifest: Manifest, questions: tuple[Question, ...], files_dir: Path, cache: VectorCache
) -> None:
    without: BenchmarkResult = await run(manifest, questions, files_dir, cache)
    assert without.speed.query_p50_ms is None
    assert without.speed.query_p95_ms is None

    sampled: BenchmarkResult = await run(
        manifest, questions, files_dir, cache, latency_embedder=HashEmbedder()
    )
    assert sampled.speed.query_p50_ms is not None
    assert sampled.speed.query_p95_ms is not None
    assert 0.0 <= sampled.speed.query_p50_ms <= sampled.speed.query_p95_ms

    single: BenchmarkResult = await run(
        manifest, questions[:1], files_dir, cache, latency_embedder=HashEmbedder()
    )
    assert single.speed.query_p50_ms == single.speed.query_p95_ms
    assert single.speed.query_p50_ms is not None


async def test_a_run_without_questions_still_reports_documents(
    manifest: Manifest, files_dir: Path, cache: VectorCache
) -> None:
    result: BenchmarkResult = await run(manifest, (), files_dir, cache)
    assert result.outcomes == ()
    assert len(result.documents) == 2
