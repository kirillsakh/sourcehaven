import statistics
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from evals.normalize import normalize
from evals.questions import GoldSpan, Question
from sourcehaven.domain.models import Evidence, ExtractedPage, PageSpan
from sourcehaven.retrieval.search import select_evidence

QUOTE_COVERAGE_THRESHOLD: Final[float] = 0.8

_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_URL, "sourcehaven-evals")
_ANSWERED_KINDS: Final[frozenset[str]] = frozenset({"answerable", "conflict"})
_RECALL_DEPTH: Final[int] = 8
_MRR_DEPTH: Final[int] = 10
_THRESHOLD_STEPS: Final[int] = 100
_PAGE_SEPARATOR: Final[str] = "\n\n"

type SpanLocation = Literal["on_page", "other_page", "across_pages", "missing"]


@dataclass(frozen=True)
class Passage:
    """A passage of a corpus document, as the splitter produced it.

    Attributes:
        document: Corpus document id.
        ordinal: Position of the passage within the document.
        normalized: `normalize(text)`, kept so that containment checks do not renormalise.
        pages: Pages the passage covers.
    """

    document: str
    ordinal: int
    text: str
    normalized: str
    pages: PageSpan

    def evidence(self, similarity: float) -> Evidence:
        """Present the passage as retrieval evidence with ids derived from its identity."""
        document_id: uuid.UUID = uuid.uuid5(_NAMESPACE, self.document)
        return Evidence(
            chunk_id=uuid.uuid5(_NAMESPACE, f"{self.document}:{self.ordinal}"),
            document_id=document_id,
            version_id=document_id,
            document_name=self.document,
            text=self.text,
            span=self.pages,
            similarity=similarity,
        )


@dataclass(frozen=True)
class Ranked:
    passage: Passage
    similarity: float


@dataclass(frozen=True)
class SpanOutcome:
    """How one gold span fared at each stage of the pipeline.

    Attributes:
        location: Where the span's text occurs in the document's extracted pages.
        split: The text was extracted but no single passage contains it.
        best_rank: Rank of the best-ranked passage containing the span, if any.
        selected: A passage containing the span is among the passages `select_evidence` chose.
        page_correct: Whether that passage's pages include the gold page; None when not selected.
        quote: The quote selected from that passage, if one was selected.
        quote_coverage: `word_coverage(span.text, quote)`, if a quote was selected.
    """

    span: GoldSpan
    location: SpanLocation
    split: bool
    best_rank: int | None
    selected: bool
    page_correct: bool | None
    quote: str | None
    quote_coverage: float | None


@dataclass(frozen=True)
class QuestionOutcome:
    """Everything the metrics need to know about one question.

    Attributes:
        top_similarity: Highest candidate similarity, None without candidates.
        covering_rank: See `covering_rank`; None for unanswerable questions.
        hit: Every gold span is contained in the passages `select_evidence` chose at threshold 0.
        candidates: The ranked candidates, most similar first.
    """

    question: Question
    top_similarity: float | None
    covering_rank: int | None
    hit: bool
    spans: tuple[SpanOutcome, ...]
    candidates: tuple[Ranked, ...]


@dataclass(frozen=True)
class Distribution:
    count: int
    minimum: float | None
    p10: float | None
    median: float | None
    p90: float | None
    maximum: float | None


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    recall_at_8: float
    refused: float


@dataclass(frozen=True)
class Metrics:
    answered_questions: int
    unanswerable_questions: int
    recall_at_8: float
    mrr_at_10: float
    extraction_coverage: float
    split_spans: int
    page_accuracy: float | None
    quote_precision: float | None
    mean_quote_coverage: float | None
    answerable_top: Distribution
    unanswerable_top: Distribution
    thresholds: list[ThresholdRow]


def contains(passage: Passage, span: GoldSpan) -> bool:
    """Whether the passage is from the span's document and holds the span's normalised text."""
    return passage.document == span.document and normalize(span.text) in passage.normalized


def covering_rank(ranking: Sequence[Passage], spans: Sequence[GoldSpan]) -> int | None:
    """Smallest 1-based rank at which every span is contained in a passage ranked at or above it.

    Returns:
        The rank, or None when some span is in no ranked passage or there are no spans.
    """
    if not spans:
        return None
    ranks: list[int] = []
    for span in spans:
        first: int | None = next(
            (rank for rank, passage in enumerate(ranking, start=1) if contains(passage, span)),
            None,
        )
        if first is None:
            return None
        ranks.append(first)
    return max(ranks)


def choose_passages(candidates: Sequence[Ranked], *, threshold: float) -> list[Ranked]:
    """The candidates the application would hand to the model at the given threshold."""
    by_chunk: dict[uuid.UUID, Ranked] = {
        ranked.passage.evidence(ranked.similarity).chunk_id: ranked for ranked in candidates
    }
    chosen: list[Evidence] = select_evidence(
        [ranked.passage.evidence(ranked.similarity) for ranked in candidates],
        threshold=threshold,
    )
    return [by_chunk[evidence.chunk_id] for evidence in chosen]


def locate_span(span: GoldSpan, pages: Sequence[ExtractedPage]) -> SpanLocation:
    """Find where a gold span's normalised text occurs in a document's extracted pages.

    Searches the gold page first, then every other page, then all pages joined in order, which
    finds spans that continue across a page break.
    """
    needle: str = normalize(span.text)
    normalized: dict[int, str] = {page.page: normalize(page.text) for page in pages}
    if needle in normalized.get(span.page, ""):
        return "on_page"
    if any(needle in text for number, text in normalized.items() if number != span.page):
        return "other_page"
    if needle in normalize(_PAGE_SEPARATOR.join(page.text for page in pages)):
        return "across_pages"
    return "missing"


def distribution(values: Sequence[float]) -> Distribution:
    """Summarise values as count, minimum, 10th percentile, median, 90th percentile and maximum.

    Percentiles are inclusive: they interpolate between the observed values.
    """
    if not values:
        return Distribution(count=0, minimum=None, p10=None, median=None, p90=None, maximum=None)
    if len(values) == 1:
        only: float = values[0]
        return Distribution(count=1, minimum=only, p10=only, median=only, p90=only, maximum=only)
    deciles: list[float] = statistics.quantiles(values, n=10, method="inclusive")
    return Distribution(
        count=len(values),
        minimum=min(values),
        p10=deciles[0],
        median=statistics.median(values),
        p90=deciles[-1],
        maximum=max(values),
    )


def threshold_table(outcomes: Sequence[QuestionOutcome]) -> list[ThresholdRow]:
    """Recall@8 and the refused share for thresholds 0.00 to 1.00 in steps of 0.01.

    Recall is the share of answered questions whose gold spans are all contained in the passages
    chosen at that threshold; refused is the share of unanswerable questions with none chosen.
    """
    answered: list[QuestionOutcome] = [o for o in outcomes if o.question.kind in _ANSWERED_KINDS]
    unanswerable: list[QuestionOutcome] = [
        o for o in outcomes if o.question.kind not in _ANSWERED_KINDS
    ]
    rows: list[ThresholdRow] = []
    for step in range(_THRESHOLD_STEPS + 1):
        threshold: float = round(step / _THRESHOLD_STEPS, 2)
        recalled: int = sum(_recalled(outcome, threshold) for outcome in answered)
        refused: int = sum(
            not choose_passages(outcome.candidates, threshold=threshold) for outcome in unanswerable
        )
        rows.append(
            ThresholdRow(
                threshold=threshold,
                recall_at_8=_share(recalled, len(answered)) or 0.0,
                refused=_share(refused, len(unanswerable)) or 0.0,
            )
        )
    return rows


def summarize(outcomes: Sequence[QuestionOutcome]) -> Metrics:
    """Compute the benchmark metrics of spec section 4.3 from per-question outcomes."""
    answered: list[QuestionOutcome] = [o for o in outcomes if o.question.kind in _ANSWERED_KINDS]
    unanswerable: list[QuestionOutcome] = [
        o for o in outcomes if o.question.kind not in _ANSWERED_KINDS
    ]
    spans: list[SpanOutcome] = [span for outcome in answered for span in outcome.spans]
    selected: list[SpanOutcome] = [span for span in spans if span.selected]
    coverages: list[float] = [
        span.quote_coverage for span in spans if span.quote_coverage is not None
    ]
    reciprocal_ranks: list[float] = [
        1 / outcome.covering_rank
        if outcome.covering_rank is not None and outcome.covering_rank <= _MRR_DEPTH
        else 0.0
        for outcome in answered
    ]
    return Metrics(
        answered_questions=len(answered),
        unanswerable_questions=len(unanswerable),
        recall_at_8=_share(sum(o.hit for o in answered), len(answered)) or 0.0,
        mrr_at_10=statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        extraction_coverage=_share(sum(s.location != "missing" for s in spans), len(spans)) or 0.0,
        split_spans=sum(span.split for span in spans),
        page_accuracy=_share(sum(s.page_correct is True for s in selected), len(selected)),
        quote_precision=_share(
            sum(coverage >= QUOTE_COVERAGE_THRESHOLD for coverage in coverages), len(coverages)
        ),
        mean_quote_coverage=statistics.fmean(coverages) if coverages else None,
        answerable_top=_top_distribution(answered),
        unanswerable_top=_top_distribution(unanswerable),
        thresholds=threshold_table(outcomes),
    )


def _recalled(outcome: QuestionOutcome, threshold: float) -> bool:
    chosen: list[Passage] = [
        ranked.passage for ranked in choose_passages(outcome.candidates, threshold=threshold)
    ]
    return all(any(contains(passage, span) for passage in chosen) for span in outcome.question.gold)


def _top_distribution(outcomes: Sequence[QuestionOutcome]) -> Distribution:
    return distribution(
        [o.top_similarity for o in outcomes if o.top_similarity is not None],
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None
