import pytest

from evals.normalize import normalize
from evals.questions import GoldSpan, Question, QuestionKind
from evals.scoring import (
    Distribution,
    Metrics,
    Passage,
    QuestionOutcome,
    Ranked,
    SpanLocation,
    SpanOutcome,
    ThresholdRow,
    choose_passages,
    contains,
    covering_rank,
    distribution,
    locate_span,
    summarize,
    threshold_table,
)
from sourcehaven.domain.models import Evidence, ExtractedPage, PageSpan


def passage(
    document: str, text: str, *, ordinal: int = 0, pages: tuple[int, int] = (1, 1)
) -> Passage:
    return Passage(
        document=document,
        ordinal=ordinal,
        text=text,
        normalized=normalize(text),
        pages=PageSpan(start=pages[0], end=pages[1]),
    )


def span_in(document: str, text: str, *, page: int = 1) -> GoldSpan:
    return GoldSpan(document=document, page=page, text=text)


def question(kind: QuestionKind, *gold: GoldSpan) -> Question:
    return Question(
        id="q",
        kind=kind,
        text="?",
        documents=("report",),
        reference_answer=None if kind == "unanswerable" else "Answer.",
        gold=gold,
    )


def span_outcome(
    span: GoldSpan,
    *,
    location: SpanLocation = "on_page",
    split: bool = False,
    selected: bool = True,
    page_correct: bool | None = True,
    quote_coverage: float | None = 0.85,
) -> SpanOutcome:
    return SpanOutcome(
        span=span,
        location=location,
        split=split,
        best_rank=1 if selected else None,
        selected=selected,
        page_correct=page_correct,
        quote=None if quote_coverage is None else "quote",
        quote_coverage=quote_coverage,
    )


def answered_outcome(
    *,
    rank: int | None,
    spans: tuple[SpanOutcome, ...] = (),
    top: float | None = 0.7,
    kind: QuestionKind = "answerable",
    candidates: tuple[Ranked, ...] = (),
    hit: bool | None = None,
) -> QuestionOutcome:
    gold: tuple[GoldSpan, ...] = tuple(outcome.span for outcome in spans) or (
        span_in("report", "x"),
    )
    return QuestionOutcome(
        question=question(kind, *gold),
        top_similarity=top,
        covering_rank=rank,
        hit=rank is not None and rank <= 8 if hit is None else hit,
        spans=spans,
        candidates=candidates,
    )


def unanswerable_outcome(
    *, candidates: tuple[Ranked, ...], top_similarity: float | None
) -> QuestionOutcome:
    return QuestionOutcome(
        question=question("unanswerable"),
        top_similarity=top_similarity,
        covering_rank=None,
        hit=False,
        spans=(),
        candidates=candidates,
    )


def test_a_passage_from_another_document_never_contains_the_span() -> None:
    span: GoldSpan = GoldSpan(document="report", page=13, text="Import dependency was 40%.")
    assert contains(passage("report", "… Import dependency was 40%. …"), span)
    assert not contains(passage("report-2024", "… Import dependency was 40%. …"), span)


def test_contains_compares_normalised_text() -> None:
    span: GoldSpan = span_in("report", "Cats — dogs, “quoted”")
    assert contains(passage("report", 'all the CATS-\ndogs, "quoted" here'), span)
    assert not contains(passage("report", "cats dogs"), span)


def test_covering_rank_needs_every_span() -> None:
    a: GoldSpan = span_in("report", "alpha")
    b: GoldSpan = span_in("report-2024", "beta")
    ranking: list[Passage] = [
        passage("report", "alpha"),
        passage("x", "noise"),
        passage("report-2024", "beta"),
    ]
    assert covering_rank(ranking, [a]) == 1 and covering_rank(ranking, [a, b]) == 3
    assert covering_rank(ranking[:2], [a, b]) is None


def test_covering_rank_without_spans_is_none() -> None:
    assert covering_rank([passage("report", "alpha")], []) is None


def test_passage_evidence_ids_are_stable_per_document_and_ordinal() -> None:
    first: Passage = passage("report", "alpha", ordinal=2, pages=(3, 4))
    same: Passage = passage("report", "other text", ordinal=2)
    other_ordinal: Passage = passage("report", "alpha", ordinal=3)
    other_document: Passage = passage("report-2024", "alpha", ordinal=2)

    evidence: Evidence = first.evidence(0.75)
    assert evidence.chunk_id == same.evidence(0.1).chunk_id
    assert evidence.chunk_id != other_ordinal.evidence(0.75).chunk_id
    assert evidence.document_id == other_ordinal.evidence(0.75).document_id
    assert evidence.document_id != other_document.evidence(0.75).document_id
    assert evidence.version_id == evidence.document_id
    assert evidence.document_name == "report" and evidence.text == "alpha"
    assert evidence.span == PageSpan(start=3, end=4) and evidence.similarity == 0.75


def test_choose_passages_applies_the_threshold_and_document_cap() -> None:
    ranked: list[Ranked] = [
        Ranked(passage("a", f"t{i}", ordinal=i), 0.9 - i / 100) for i in range(6)
    ] + [Ranked(passage("b", "u"), 0.5)]
    chosen: list[Ranked] = choose_passages(ranked, threshold=0.0)
    assert (
        sum(r.passage.document == "a" for r in chosen) == 4 and chosen[-1].passage.document == "b"
    )
    assert choose_passages(ranked, threshold=0.95) == []


def test_choose_passages_returns_the_same_ranked_objects_most_similar_first() -> None:
    low: Ranked = Ranked(passage("a", "low", ordinal=0), 0.2)
    high: Ranked = Ranked(passage("a", "high", ordinal=1), 0.8)
    chosen: list[Ranked] = choose_passages([low, high], threshold=0.1)
    assert chosen == [high, low] and chosen[0] is high and chosen[1] is low


def test_locate_span() -> None:
    pages: list[ExtractedPage] = [
        ExtractedPage(1, "Intro text.", True),
        ExtractedPage(2, "The answer is 42.", True),
        ExtractedPage(3, "Starts here and", True),
        ExtractedPage(4, "ends there.", True),
    ]
    assert locate_span(GoldSpan("d", 2, "the answer is 42"), pages) == "on_page"
    assert locate_span(GoldSpan("d", 1, "the answer is 42"), pages) == "other_page"
    assert locate_span(GoldSpan("d", 3, "here and ends there"), pages) == "across_pages"
    assert locate_span(GoldSpan("d", 2, "not present"), pages) == "missing"


def test_distribution_of_values() -> None:
    assert distribution([]) == Distribution(
        count=0, minimum=None, p10=None, median=None, p90=None, maximum=None
    )
    assert distribution([0.4]) == Distribution(
        count=1, minimum=0.4, p10=0.4, median=0.4, p90=0.4, maximum=0.4
    )
    spread: Distribution = distribution([float(value) for value in range(1, 12)])
    assert spread.count == 11 and spread.minimum == 1.0 and spread.maximum == 11.0
    assert spread.median == 6.0
    assert spread.p10 == pytest.approx(2.0) and spread.p90 == pytest.approx(10.0)


def test_summarize_on_hand_made_outcomes() -> None:
    hit_span: GoldSpan = span_in("report", "alpha", page=2)
    missed_span: GoldSpan = span_in("report", "beta", page=3)
    outcomes: list[QuestionOutcome] = [
        answered_outcome(
            rank=2,
            top=0.8,
            spans=(span_outcome(hit_span, quote_coverage=0.85),),
        ),
        answered_outcome(
            rank=None,
            top=0.4,
            spans=(
                span_outcome(
                    missed_span,
                    location="missing",
                    selected=False,
                    page_correct=None,
                    quote_coverage=None,
                ),
            ),
        ),
        unanswerable_outcome(candidates=(Ranked(passage("a", "x"), 0.3),), top_similarity=0.3),
        unanswerable_outcome(candidates=(Ranked(passage("a", "y"), 0.6),), top_similarity=0.6),
    ]
    metrics: Metrics = summarize(outcomes)
    assert metrics.answered_questions == 2 and metrics.unanswerable_questions == 2
    assert metrics.recall_at_8 == 0.5 and metrics.mrr_at_10 == 0.25
    assert metrics.extraction_coverage == 0.5 and metrics.split_spans == 0
    assert metrics.page_accuracy == 1.0
    assert metrics.quote_precision == 1.0  # the hit's only span has coverage 0.85
    assert metrics.mean_quote_coverage == pytest.approx(0.85)
    assert metrics.answerable_top.count == 2 and metrics.answerable_top.maximum == 0.8
    assert metrics.unanswerable_top.count == 2 and metrics.unanswerable_top.median == pytest.approx(
        0.45
    )
    assert len(metrics.thresholds) == 101


def test_conflict_questions_count_as_answered_and_spans_individually() -> None:
    spans: tuple[SpanOutcome, ...] = (
        span_outcome(span_in("report", "alpha"), split=True, quote_coverage=0.9, page_correct=True),
        span_outcome(
            span_in("report-2024", "beta"),
            location="across_pages",
            quote_coverage=0.5,
            page_correct=False,
        ),
    )
    metrics: Metrics = summarize([answered_outcome(rank=1, kind="conflict", spans=spans)])
    assert metrics.answered_questions == 1 and metrics.recall_at_8 == 1.0
    assert metrics.split_spans == 1
    assert metrics.extraction_coverage == 1.0
    assert metrics.page_accuracy == 0.5
    assert metrics.quote_precision == 0.5
    assert metrics.mean_quote_coverage == pytest.approx(0.7)


def test_rank_beyond_ten_scores_zero_mrr() -> None:
    metrics: Metrics = summarize(
        [
            answered_outcome(rank=10, hit=False),
            answered_outcome(rank=11, hit=False),
            answered_outcome(rank=1),
        ]
    )
    assert metrics.mrr_at_10 == pytest.approx((0.1 + 0.0 + 1.0) / 3)
    assert metrics.recall_at_8 == pytest.approx(1 / 3)


def test_summarize_without_answered_questions_or_selected_spans() -> None:
    metrics: Metrics = summarize([unanswerable_outcome(candidates=(), top_similarity=None)])
    assert metrics.answered_questions == 0 and metrics.unanswerable_questions == 1
    assert metrics.recall_at_8 == 0.0 and metrics.mrr_at_10 == 0.0
    assert metrics.extraction_coverage == 0.0 and metrics.split_spans == 0
    assert metrics.page_accuracy is None
    assert metrics.quote_precision is None and metrics.mean_quote_coverage is None
    assert metrics.answerable_top.count == 0 and metrics.answerable_top.median is None
    assert all(row.recall_at_8 == 0.0 for row in metrics.thresholds)
    assert metrics.thresholds[0].refused == 1.0


def test_question_without_candidates_or_with_negative_similarity() -> None:
    outcome: QuestionOutcome = unanswerable_outcome(candidates=(), top_similarity=None)
    negative: QuestionOutcome = unanswerable_outcome(
        candidates=(Ranked(passage("a", "x"), -0.2),), top_similarity=-0.2
    )
    answered_hit: QuestionOutcome = answered_outcome(
        rank=1, spans=(span_outcome(span_in("report", "alpha")),), top=0.9
    )
    metrics: Metrics = summarize([answered_hit, outcome, negative])
    assert metrics.unanswerable_top.count == 1 and metrics.unanswerable_top.minimum == -0.2
    assert metrics.thresholds[0].refused == 1.0  # both refused at threshold 0.00


def test_threshold_table_rows() -> None:
    gold_a: GoldSpan = span_in("report", "alpha")
    gold_b: GoldSpan = span_in("report", "beta")
    outcomes: list[QuestionOutcome] = [
        answered_outcome(
            rank=1,
            spans=(span_outcome(gold_a),),
            candidates=(
                Ranked(passage("report", "alpha", ordinal=0), 0.6),
                Ranked(passage("report", "noise", ordinal=1), 0.3),
            ),
        ),
        answered_outcome(
            rank=1,
            spans=(span_outcome(gold_b),),
            candidates=(Ranked(passage("report", "beta", ordinal=2), 0.4),),
        ),
        unanswerable_outcome(
            candidates=(Ranked(passage("report", "p", ordinal=3), 0.55),), top_similarity=0.55
        ),
        unanswerable_outcome(
            candidates=(Ranked(passage("report", "q", ordinal=4), 0.2),), top_similarity=0.2
        ),
    ]
    rows: list[ThresholdRow] = threshold_table(outcomes)
    assert len(rows) == 101 and rows[0].threshold == 0.0 and rows[-1].threshold == 1.0
    assert [row.threshold for row in rows[:3]] == [0.0, 0.01, 0.02]
    assert (rows[0].recall_at_8, rows[0].refused) == (1.0, 0.0)
    assert (rows[30].recall_at_8, rows[30].refused) == (1.0, 0.5)
    assert (rows[50].recall_at_8, rows[50].refused) == (0.5, 0.5)
    assert (rows[60].recall_at_8, rows[60].refused) == (0.5, 1.0)  # 0.6 is inclusive
    assert (rows[100].recall_at_8, rows[100].refused) == (0.0, 1.0)


def test_threshold_table_recall_needs_every_gold_span_among_the_chosen() -> None:
    gold: tuple[GoldSpan, ...] = (span_in("report", "alpha"), span_in("report-2024", "beta"))
    candidates: tuple[Ranked, ...] = (
        Ranked(passage("report", "alpha", ordinal=0), 0.9),
        Ranked(passage("report-2024", "beta", ordinal=0), 0.5),
    )
    outcome: QuestionOutcome = answered_outcome(
        rank=2,
        kind="conflict",
        spans=tuple(span_outcome(span) for span in gold),
        candidates=candidates,
    )
    rows: list[ThresholdRow] = threshold_table([outcome])
    assert rows[50].recall_at_8 == 1.0 and rows[51].recall_at_8 == 0.0
