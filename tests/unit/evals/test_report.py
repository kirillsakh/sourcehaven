import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.corpus import CorpusDocument
from evals.normalize import normalize
from evals.pipeline import BenchmarkResult, DocumentPassages, SpeedFigures
from evals.questions import GoldSpan, Question
from evals.report import RunContext, render_review_sheet, render_summary, write_report
from evals.scoring import (
    Metrics,
    Passage,
    QuestionOutcome,
    Ranked,
    SpanLocation,
    SpanOutcome,
    summarize,
)
from sourcehaven.domain.models import ExtractedPage, ExtractedSource, PageSpan
from tests.support.embeddings import make_config

_HIT_SPAN: GoldSpan = GoldSpan(document="facts", page=1, text="The warranty is 24 months.")
_MISSED_SPAN: GoldSpan = GoldSpan(document="facts", page=2, text="Returns are free for 30 days.")
_LOST_SPAN: GoldSpan = GoldSpan(document="facts", page=3, text="Shipping takes two days.")

QUESTIONS: tuple[Question, ...] = (
    Question(
        id="q-1",
        kind="answerable",
        text="How long is the warranty?",
        documents=("facts",),
        reference_answer="The warranty is 24 months.",
        gold=(_HIT_SPAN,),
    ),
    Question(
        id="q-2",
        kind="answerable",
        text="What are the return and shipping terms?",
        documents=("facts", "other"),
        reference_answer="Returns are free and shipping takes two days.",
        gold=(_MISSED_SPAN, _LOST_SPAN),
    ),
    Question(
        id="q-3",
        kind="unanswerable",
        text="What is the capital of Peru?",
        documents=("facts",),
        reference_answer=None,
        gold=(),
    ),
)

_PASSAGE: Passage = Passage(
    document="facts",
    ordinal=0,
    text=_HIT_SPAN.text,
    normalized=normalize(_HIT_SPAN.text),
    pages=PageSpan(start=1, end=1),
)

CONTEXT: RunContext = RunContext(
    created_at=datetime(2026, 11, 21, 9, 30, 5, tzinfo=UTC),
    git_commit="abc123-dirty",
    corpus_version=3,
    questions_sha256="f" * 64,
    label="test",
    tokenizer_file=Path("/cache/tokenizer.json"),
    tokenizer_sha256="e" * 64,
)


def span_outcome(
    span: GoldSpan,
    location: SpanLocation,
    *,
    split: bool = False,
    best_rank: int | None = None,
    best_document_rank: int | None = None,
    selected: bool = False,
) -> SpanOutcome:
    return SpanOutcome(
        span=span,
        location=location,
        split=split,
        best_rank=best_rank,
        best_document_rank=best_document_rank,
        selected=selected,
        page_correct=True if selected else None,
        quote=span.text if selected else None,
        quote_coverage=1.0 if selected else None,
    )


def make_result() -> BenchmarkResult:
    outcomes: tuple[QuestionOutcome, ...] = (
        QuestionOutcome(
            question=QUESTIONS[0],
            top_similarity=0.91,
            covering_rank=1,
            hit=True,
            spans=(span_outcome(_HIT_SPAN, "on_page", best_rank=1, selected=True),),
            candidates=(Ranked(_PASSAGE, 0.91),),
        ),
        QuestionOutcome(
            question=QUESTIONS[1],
            top_similarity=0.62,
            covering_rank=None,
            hit=False,
            spans=(
                span_outcome(_MISSED_SPAN, "other_page", best_rank=12, best_document_rank=3),
                span_outcome(_LOST_SPAN, "across_pages", split=True),
            ),
            candidates=(Ranked(_PASSAGE, 0.62),),
        ),
        QuestionOutcome(
            question=QUESTIONS[2],
            top_similarity=0.35,
            covering_rank=None,
            hit=False,
            spans=(),
            candidates=(),
        ),
    )
    document: CorpusDocument = CorpusDocument(
        id="facts",
        title="Facts",
        author="Test",
        url="https://example.test/facts.pdf",
        sha256="0" * 64,
        size_bytes=10,
        page_count=3,
        licence="Test",
        licence_url="https://example.test/licence",
        layout="plain",
        page_range=None,
        selected_by_default=True,
    )
    source: ExtractedSource = ExtractedSource(
        pages=(ExtractedPage(page=1, text=_HIT_SPAN.text, has_text_layer=True),),
        page_count=3,
        parser_name="pypdf",
        parser_version="9.9.9",
    )
    return BenchmarkResult(
        outcomes=outcomes,
        documents=(
            DocumentPassages(
                document=document, source=source, passages=(_PASSAGE,), extract_seconds=0.25
            ),
        ),
        speed=SpeedFigures(
            extract_seconds_per_page=0.01,
            passages_per_page=2.5,
            embedded_passages=7,
            passages_per_second=140.0,
            query_p50_ms=12.5,
            query_p95_ms=None,
        ),
        config=make_config(),
    )


def test_review_sheet_lists_every_span_and_summary_counts() -> None:
    locations: dict[tuple[str, int], SpanLocation] = {
        ("q-1", 0): "on_page",
        ("q-2", 0): "other_page",
        ("q-2", 1): "missing",
    }

    sheet: str = render_review_sheet(QUESTIONS, locations)

    assert "on_page: 1" in sheet
    assert "other_page: 1" in sheet
    assert "across_pages: 0" in sheet
    assert "missing: 1" in sheet
    for question in QUESTIONS:
        assert question.id in sheet
        assert question.text in sheet
    assert "The warranty is 24 months." in sheet
    assert "Returns are free for 30 days." in sheet
    assert "Shipping takes two days." in sheet
    assert "facts, other" in sheet
    assert "unanswerable" in sheet


def test_review_sheet_places_each_location_beside_its_span() -> None:
    locations: dict[tuple[str, int], SpanLocation] = {
        ("q-1", 0): "on_page",
        ("q-2", 0): "other_page",
        ("q-2", 1): "missing",
    }

    sheet: str = render_review_sheet(QUESTIONS, locations)

    line: str = next(row for row in sheet.splitlines() if "Shipping takes two days." in row)
    assert "missing" in line


def test_summary_lists_misses_with_their_cause() -> None:
    result: BenchmarkResult = make_result()

    summary: str = render_summary(result, summarize(result.outcomes), CONTEXT)

    misses: str = summary.split("## Misses", maxsplit=1)[1]
    assert "q-2" in misses
    assert "q-1" not in misses
    assert "q-3" not in misses
    assert "other_page" in misses
    assert "best_rank=12" in misses
    assert "best_document_rank=3" in misses
    assert "cause=ranked too low" in misses
    assert "across_pages" in misses
    assert "split=yes" in misses
    assert "best_document_rank=n/a" in misses
    assert "cause=split" in misses


def test_miss_cause_distinguishes_each_stage_of_the_pipeline() -> None:
    cases: list[tuple[SpanOutcome, str]] = [
        (span_outcome(_MISSED_SPAN, "missing"), "not extracted"),
        (span_outcome(_MISSED_SPAN, "on_page", split=True), "split"),
        (
            span_outcome(_MISSED_SPAN, "on_page", best_rank=8, best_document_rank=2),
            "dropped by the per-document cap",
        ),
        (
            span_outcome(_MISSED_SPAN, "on_page", best_rank=9, best_document_rank=2),
            "ranked too low",
        ),
        (span_outcome(_HIT_SPAN, "on_page", best_rank=1, selected=True), "selected"),
    ]
    for span, cause in cases:
        question: Question = replace(QUESTIONS[1], gold=(span.span,))
        missed: QuestionOutcome = QuestionOutcome(
            question=question,
            top_similarity=0.5,
            covering_rank=None,
            hit=False,
            spans=(span,),
            candidates=(),
        )
        result: BenchmarkResult = replace(make_result(), outcomes=(missed,))

        summary: str = render_summary(result, summarize(result.outcomes), CONTEXT)

        assert f"cause={cause}" in summary.split("## Misses", maxsplit=1)[1]


def test_summary_states_the_context_configuration_and_metrics() -> None:
    result: BenchmarkResult = make_result()
    metrics: Metrics = summarize(result.outcomes)

    summary: str = render_summary(result, metrics, CONTEXT)

    assert "2026-11-21T09:30:05+00:00" in summary
    assert "test" in summary
    assert "abc123-dirty" in summary
    assert "f" * 64 in summary
    assert "pypdf 9.9.9" in summary
    assert "/cache/tokenizer.json" in summary
    assert "e" * 64 in summary
    assert result.config.model_id in summary
    assert "Recall@8" in summary
    assert f"{metrics.recall_at_8:.1%}" in summary
    assert "MRR@10" in summary
    assert "n/a" in summary


def test_summary_threshold_table_shows_every_fifth_hundredth() -> None:
    result: BenchmarkResult = make_result()

    summary: str = render_summary(result, summarize(result.outcomes), CONTEXT)

    rows: list[str] = [line for line in summary.splitlines() if line.startswith("| 0.")]
    thresholds: list[str] = [row.split("|")[1].strip() for row in rows]
    assert thresholds[0] == "0.00"
    assert thresholds[1] == "0.05"
    assert len(thresholds) == 20
    assert "| 1.00 " in summary
    assert "| 0.01 " not in summary


def test_report_json_round_trips_the_metrics(tmp_path: Path) -> None:
    result: BenchmarkResult = make_result()
    metrics: Metrics = summarize(result.outcomes)

    directory: Path = write_report(result, metrics, CONTEXT, tmp_path)

    data: dict[str, Any] = json.loads((directory / "report.json").read_text())
    assert directory == tmp_path / "20261121T093005Z-test"
    assert (directory / "summary.md").is_file()
    assert data["metrics"]["recall_at_8"] == metrics.recall_at_8
    assert data["metrics"]["mrr_at_10"] == metrics.mrr_at_10
    assert len(data["metrics"]["thresholds"]) == 101
    assert data["context"]["label"] == "test"
    assert data["context"]["corpus_version"] == 3
    assert data["context"]["questions_sha256"] == "f" * 64
    assert data["context"]["created_at"] == "2026-11-21T09:30:05+00:00"
    assert data["context"]["tokenizer_file"] == "/cache/tokenizer.json"
    assert data["context"]["tokenizer_sha256"] == "e" * 64
    assert data["parser"] == {"name": "pypdf", "version": "9.9.9"}
    assert data["config"]["model_id"] == result.config.model_id
    assert data["speed"]["query_p95_ms"] is None
    assert data["documents"] == [
        {"id": "facts", "pages": 1, "passages": 1, "extract_seconds": 0.25}
    ]


def test_report_json_keeps_every_outcome_without_candidates(tmp_path: Path) -> None:
    result: BenchmarkResult = make_result()

    directory: Path = write_report(result, summarize(result.outcomes), CONTEXT, tmp_path)

    data: dict[str, Any] = json.loads((directory / "report.json").read_text())
    outcomes: list[dict[str, Any]] = data["outcomes"]
    assert [item["question"]["id"] for item in outcomes] == ["q-1", "q-2", "q-3"]
    assert all("candidates" not in item for item in outcomes)
    assert outcomes[1]["spans"][0]["location"] == "other_page"
    assert outcomes[1]["spans"][0]["best_rank"] == 12
    assert outcomes[1]["spans"][1]["split"] is True
    assert outcomes[0]["hit"] is True
    assert outcomes[2]["spans"] == []
