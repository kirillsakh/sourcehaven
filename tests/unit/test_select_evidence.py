from uuid import UUID, uuid4

from sourcehaven.domain.models import Evidence, PageSpan
from sourcehaven.retrieval.search import select_evidence

A: UUID = uuid4()
B: UUID = uuid4()


def ev(*, doc: UUID, sim: float) -> Evidence:
    return Evidence(
        chunk_id=uuid4(),
        document_id=doc,
        version_id=uuid4(),
        document_name="doc.pdf",
        text="text",
        span=PageSpan(start=1, end=1),
        similarity=sim,
    )


def test_per_document_cap_only_with_multiple_documents() -> None:
    single: list[Evidence] = [ev(doc=A, sim=1 - i / 100) for i in range(10)]
    assert len(select_evidence(single, threshold=0.0)) == 8
    mixed: list[Evidence] = [ev(doc=A, sim=0.9 - i / 100) for i in range(6)] + [ev(doc=B, sim=0.5)]
    chosen: list[Evidence] = select_evidence(mixed, threshold=0.0)
    assert sum(1 for e in chosen if e.document_id == A) == 4 and chosen[-1].document_id == B


def test_threshold_filters_everything() -> None:
    assert select_evidence([ev(doc=A, sim=0.2)], threshold=0.3) == []


def test_threshold_is_inclusive() -> None:
    exactly: Evidence = ev(doc=A, sim=0.5)
    assert select_evidence([exactly, ev(doc=A, sim=0.4999)], threshold=0.5) == [exactly]


def test_cap_counts_only_candidates_that_pass_the_threshold() -> None:
    weak_b: Evidence = ev(doc=B, sim=0.1)
    candidates: list[Evidence] = [ev(doc=A, sim=0.9 - i / 100) for i in range(6)] + [weak_b]
    chosen: list[Evidence] = select_evidence(candidates, threshold=0.5)
    assert len(chosen) == 6


def test_total_limit_applies_across_documents_in_similarity_order() -> None:
    a_side: list[Evidence] = [ev(doc=A, sim=0.9 - i / 100) for i in range(3)]
    b_side: list[Evidence] = [ev(doc=B, sim=0.895 - i / 100) for i in range(3)]
    chosen: list[Evidence] = select_evidence(b_side + a_side, max_total=5, threshold=0.0)
    assert chosen == [a_side[0], b_side[0], a_side[1], b_side[1], a_side[2]]


def test_candidates_are_ordered_by_similarity_even_if_given_unsorted() -> None:
    low: Evidence = ev(doc=A, sim=0.3)
    high: Evidence = ev(doc=A, sim=0.7)
    assert select_evidence([low, high], threshold=0.0) == [high, low]
