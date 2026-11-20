from uuid import UUID

import pytest

from sourcehaven.domain.models import Evidence, PageSpan
from tests.support.visitors import ReadyVisitorFactory, TwoReadyVisitors

pytestmark = pytest.mark.integration

# Each page of multipage_en.pdf has 23 to 30 whitespace tokens, so with 40 per chunk every page
# becomes its own chunk. With the default 400 the whole document is one chunk spanning all pages.
ONE_CHUNK_PER_PAGE: dict[str, object] = {"chunk_tokens": 40, "chunk_overlap": 5}


async def test_retrieves_fact_with_page(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, doc_ids = await ready_visitor(
        "facts_small_en.pdf", "multipage_en.pdf", settings_overrides=ONE_CHUNK_PER_PAGE
    )
    results: list[Evidence] = await visitor.search("When was the bridge completed?", doc_ids)
    assert results[0].span == PageSpan(start=4, end=4) and "1931" in results[0].text


async def test_results_are_ordered_by_similarity_and_labelled(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, doc_ids = await ready_visitor("facts_small_en.pdf", "multipage_en.pdf")
    results: list[Evidence] = await visitor.search("When was the bridge completed?", doc_ids)
    similarities: list[float] = [result.similarity for result in results]
    assert similarities == sorted(similarities, reverse=True)
    assert all(0.0 <= similarity <= 1.0 for similarity in similarities)
    assert {result.document_name for result in results} == {
        "facts_small_en.pdf",
        "multipage_en.pdf",
    }


async def test_only_selected_documents_are_searched(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (facts, _) = await ready_visitor("facts_small_en.pdf", "multipage_en.pdf")
    results: list[Evidence] = await visitor.search("bridge completed 1931", [facts])
    assert results
    assert all(str(result.document_id) == facts for result in results)


async def test_no_selected_documents_returns_nothing(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, _ = await ready_visitor("facts_small_en.pdf")
    assert await visitor.search("anything", []) == []


async def test_foreign_document_ids_return_nothing(two_ready_visitors: TwoReadyVisitors) -> None:
    (x, x_docs), (y, _) = two_ready_visitors
    assert await x.search("ALPHA-7731 code", x_docs)  # control: the owner does find it
    assert await y.search("ALPHA-7731 code", x_docs) == []


async def test_rls_blocks_even_without_application_filter(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, _), (y, _) = two_ready_visitors
    x_chunks: list[UUID] = await x.search_unfiltered("ALPHA-7731 code")
    y_chunks: list[UUID] = await y.search_unfiltered("ALPHA-7731 code")
    assert x_chunks and y_chunks  # each sees its own rows, so an empty overlap is meaningful
    assert not set(x_chunks) & set(y_chunks)
    assert not await y.chunk_texts_contain("ALPHA-7731")
