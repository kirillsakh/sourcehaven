import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from evals.pipeline import BenchmarkResult
from evals.questions import Question
from evals.scoring import Distribution, Metrics, QuestionOutcome, SpanLocation, SpanOutcome
from sourcehaven.domain.models import ExtractedSource

LOCATIONS: Final[tuple[SpanLocation, ...]] = ("on_page", "other_page", "across_pages", "missing")

_ANSWERED_KINDS: Final[frozenset[str]] = frozenset({"answerable", "conflict"})
_TIMESTAMP_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"
_THRESHOLD_STRIDE: Final[int] = 5
_NOT_AVAILABLE: Final[str] = "n/a"


@dataclass(frozen=True)
class RunContext:
    """What identifies a benchmark run, recorded in every report.

    Attributes:
        created_at: Timezone-aware UTC start of the run; names the report directory.
        git_commit: Revision of the checkout, with `-dirty` when it has uncommitted changes.
        corpus_version: Version of the corpus manifest.
        questions_sha256: SHA-256 of the question file.
        label: Free name of the run, appended to the report directory.
    """

    created_at: datetime
    git_commit: str
    corpus_version: int
    questions_sha256: str
    label: str


def count_locations(locations: Mapping[tuple[str, int], SpanLocation]) -> dict[SpanLocation, int]:
    """Count spans per location, with zero for locations that no span has."""
    counts: dict[SpanLocation, int] = dict.fromkeys(LOCATIONS, 0)
    for location in locations.values():
        counts[location] += 1
    return counts


def write_report(
    result: BenchmarkResult, metrics: Metrics, context: RunContext, reports_dir: Path
) -> Path:
    """Write `report.json` and `summary.md` of a run into a new directory under `reports_dir`.

    Returns:
        The directory `<reports_dir>/<UTC timestamp>-<label>`.
    """
    directory: Path = (
        reports_dir / f"{context.created_at.strftime(_TIMESTAMP_FORMAT)}-{context.label}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(_report_data(result, metrics, context), indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (directory / "summary.md").write_text(
        render_summary(result, metrics, context), encoding="utf-8"
    )
    return directory


def render_summary(result: BenchmarkResult, metrics: Metrics, context: RunContext) -> str:
    """Render the human-readable summary of a run as Markdown."""
    config: Mapping[str, Any] = dataclasses.asdict(result.config)
    lines: list[str] = [
        f"# Benchmark run {context.label}",
        "",
        f"- Created: {context.created_at.isoformat()}",
        f"- Git commit: {context.git_commit}",
        f"- Corpus version: {context.corpus_version}",
        f"- Question file SHA-256: {context.questions_sha256}",
        f"- Parser: {_parser_label(result)}",
        "",
        "## Configuration",
        "",
        *[f"- {name}: {value!r}" for name, value in config.items()],
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Answered questions | {metrics.answered_questions} |",
        f"| Unanswerable questions | {metrics.unanswerable_questions} |",
        f"| Recall@8 | {_percent(metrics.recall_at_8)} |",
        f"| MRR@10 | {metrics.mrr_at_10:.3f} |",
        f"| Extraction coverage | {_percent(metrics.extraction_coverage)} |",
        f"| Split spans | {metrics.split_spans} |",
        f"| Page accuracy | {_percent(metrics.page_accuracy)} |",
        f"| Quote precision | {_percent(metrics.quote_precision)} |",
        f"| Mean quote coverage | {_percent(metrics.mean_quote_coverage)} |",
        "",
        "## Top similarity",
        "",
        "| Questions | Count | Min | P10 | Median | P90 | Max |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        _distribution_row("Answerable", metrics.answerable_top),
        _distribution_row("Unanswerable", metrics.unanswerable_top),
        "",
        "## Evidence threshold",
        "",
        "| Threshold | Recall@8 | Refused |",
        "| --- | --- | --- |",
        *[
            f"| {row.threshold:.2f} | {_percent(row.recall_at_8)} | {_percent(row.refused)} |"
            for row in metrics.thresholds
            if round(row.threshold * 100) % _THRESHOLD_STRIDE == 0
        ],
        "",
        "## Speed",
        "",
        f"- Extraction: {result.speed.extract_seconds_per_page:.3f} s per page",
        f"- Passages per page: {result.speed.passages_per_page:.2f}",
        f"- Passages embedded: {result.speed.embedded_passages}",
        f"- Embedding rate: {_number(result.speed.passages_per_second, ' passages/s')}",
        f"- Query latency median: {_number(result.speed.query_p50_ms, ' ms')}",
        f"- Query latency P95: {_number(result.speed.query_p95_ms, ' ms')}",
        "",
        "## Misses",
        "",
        *_miss_lines(result.outcomes),
    ]
    return "\n".join(lines) + "\n"


def render_review_sheet(
    questions: Sequence[Question], locations: Mapping[tuple[str, int], SpanLocation]
) -> str:
    """Render the gold-span review sheet as Markdown.

    Args:
        questions: The validated questions.
        locations: Where each span was found, keyed by question id and span index.

    Raises:
        KeyError: If a span of a question has no entry in `locations`.
    """
    counts: dict[SpanLocation, int] = count_locations(locations)
    lines: list[str] = [
        "# Review sheet",
        "",
        "Spans per location in the extracted text:",
        "",
        *[f"- {location}: {counts[location]}" for location in LOCATIONS],
    ]
    for question in questions:
        lines += [
            "",
            f"## {question.id}",
            "",
            f"- Kind: {question.kind}",
            f"- Question: {question.text}",
            f"- Documents: {', '.join(question.documents)}",
            f"- Reference answer: {question.reference_answer or _NOT_AVAILABLE}",
        ]
        if question.gold:
            lines.append("- Gold spans:")
        for index, span in enumerate(question.gold):
            location: SpanLocation = locations[(question.id, index)]
            lines.append(
                f"  {index + 1}. [{location}] {span.document}, page {span.page}: "
                f"{_one_line(span.text)}"
            )
    return "\n".join(lines) + "\n"


def _report_data(result: BenchmarkResult, metrics: Metrics, context: RunContext) -> dict[str, Any]:
    parser: ExtractedSource | None = _parser(result)
    return {
        "context": dataclasses.asdict(context),
        "parser": {
            "name": parser.parser_name if parser else None,
            "version": parser.parser_version if parser else None,
        },
        "config": dataclasses.asdict(result.config),
        "metrics": dataclasses.asdict(metrics),
        "speed": dataclasses.asdict(result.speed),
        "documents": [
            {
                "id": item.document.id,
                "pages": len(item.source.pages),
                "passages": len(item.passages),
                "extract_seconds": item.extract_seconds,
            }
            for item in result.documents
        ],
        "outcomes": [_outcome_data(outcome) for outcome in result.outcomes],
    }


def _outcome_data(outcome: QuestionOutcome) -> dict[str, Any]:
    data: dict[str, Any] = dataclasses.asdict(dataclasses.replace(outcome, candidates=()))
    del data["candidates"]
    return data


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _parser(result: BenchmarkResult) -> ExtractedSource | None:
    return result.documents[0].source if result.documents else None


def _parser_label(result: BenchmarkResult) -> str:
    parser: ExtractedSource | None = _parser(result)
    return f"{parser.parser_name} {parser.parser_version}" if parser else _NOT_AVAILABLE


def _miss_lines(outcomes: Sequence[QuestionOutcome]) -> list[str]:
    missed: list[QuestionOutcome] = [
        o for o in outcomes if o.question.kind in _ANSWERED_KINDS and not o.hit
    ]
    if not missed:
        return ["No answered question missed."]
    lines: list[str] = []
    for outcome in missed:
        lines.append(f"- {outcome.question.id} ({outcome.question.kind}): {outcome.question.text}")
        lines += [_span_line(index, span) for index, span in enumerate(outcome.spans, start=1)]
    return lines


def _span_line(index: int, span: SpanOutcome) -> str:
    return (
        f"  - span {index} ({span.span.document}, page {span.span.page}): "
        f"location={span.location}, split={'yes' if span.split else 'no'}, "
        f"best_rank={span.best_rank if span.best_rank is not None else _NOT_AVAILABLE}"
    )


def _distribution_row(label: str, values: Distribution) -> str:
    cells: list[str] = [
        _number(value, "")
        for value in (values.minimum, values.p10, values.median, values.p90, values.maximum)
    ]
    return f"| {label} | {values.count} | {' | '.join(cells)} |"


def _percent(value: float | None) -> str:
    return _NOT_AVAILABLE if value is None else f"{value:.1%}"


def _number(value: float | None, unit: str) -> str:
    return _NOT_AVAILABLE if value is None else f"{value:.3f}{unit}"


def _one_line(text: str) -> str:
    return " ".join(text.split())
