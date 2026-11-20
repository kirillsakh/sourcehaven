from itertools import pairwise

import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from sourcehaven.domain.models import ChunkDraft, ExtractedPage, PageSpan
from sourcehaven.embeddings.hashing import WhitespaceTokenCounter
from sourcehaven.ingestion.chunking import chunk_pages


class CharacterTokenCounter:
    def count(self, text: str) -> int:
        return len(text)


class OvercountingTokenCounter:
    """Counts a joined text as one token more than the sum of its single-word parts."""

    def count(self, text: str) -> int:
        words: int = len(text.split())
        return words + 1 if words > 1 else words


def pages(*texts: str) -> list[ExtractedPage]:
    return [
        ExtractedPage(page=i + 1, text=t, has_text_layer=bool(t.strip()))
        for i, t in enumerate(texts)
    ]


def joined_text(source: list[ExtractedPage]) -> str:
    return "\n\n".join(p.text for p in source if p.has_text_layer)


def assert_tiles_document(drafts: list[ChunkDraft], joined: str) -> None:
    covered: set[int] = set()
    for draft in drafts:
        assert joined[draft.char_start : draft.char_end] == draft.text
        covered.update(range(draft.char_start, draft.char_end))
    missing: list[int] = [i for i, ch in enumerate(joined) if not ch.isspace() and i not in covered]
    assert missing == []
    assert drafts[-1].char_end == len(joined.rstrip())
    assert drafts[0].char_start == len(joined) - len(joined.lstrip())


def test_chunks_respect_token_limit() -> None:
    text: str = " ".join(f"word{i}." for i in range(2000))
    drafts: list[ChunkDraft] = chunk_pages(
        pages(text), WhitespaceTokenCounter(), chunk_tokens=400, chunk_overlap=60
    )
    assert len(drafts) >= 5
    assert all(d.token_count <= 400 for d in drafts)
    assert [d.ordinal for d in drafts] == list(range(len(drafts)))


def test_offsets_slice_the_joined_text() -> None:
    source: list[ExtractedPage] = pages("Alpha one.\n\nAlpha two.", "Beta three.")
    joined: str = "Alpha one.\n\nAlpha two.\n\nBeta three."
    for draft in chunk_pages(source, WhitespaceTokenCounter(), chunk_tokens=3, chunk_overlap=0):
        assert joined[draft.char_start : draft.char_end] == draft.text


def test_page_spans_and_cross_page_chunks() -> None:
    drafts: list[ChunkDraft] = chunk_pages(
        pages("first page text", "second page text"),
        WhitespaceTokenCounter(),
        chunk_tokens=400,
        chunk_overlap=0,
    )
    assert drafts[0].span == PageSpan(start=1, end=2)


def test_pages_without_text_layer_are_skipped_but_numbering_kept() -> None:
    drafts: list[ChunkDraft] = chunk_pages(
        pages("intro", "", "MARKER three"),
        WhitespaceTokenCounter(),
        chunk_tokens=1,
        chunk_overlap=0,
    )
    marker: ChunkDraft = next(d for d in drafts if "MARKER" in d.text)
    assert marker.span == PageSpan(start=3, end=3)


def test_offsets_hold_with_overlap_and_repeated_text() -> None:
    source: list[ExtractedPage] = pages(
        " ".join(["repeat."] * 300), " ".join(f"w{i}." for i in range(300))
    )
    joined: str = joined_text(source)
    counter: WhitespaceTokenCounter = WhitespaceTokenCounter()
    drafts: list[ChunkDraft] = chunk_pages(source, counter, chunk_tokens=40, chunk_overlap=10)
    assert len(drafts) > 10
    for draft in drafts:
        assert joined[draft.char_start : draft.char_end] == draft.text
        assert draft.token_count == counter.count(draft.text) <= 40
    starts: list[int] = [d.char_start for d in drafts]
    assert starts == sorted(set(starts))
    assert_tiles_document(drafts, joined)


def test_periodic_text_advances_by_chunk_minus_overlap() -> None:
    word: str = "repeat. "
    text: str = " ".join(["repeat."] * 300)
    drafts: list[ChunkDraft] = chunk_pages(
        pages(text), WhitespaceTokenCounter(), chunk_tokens=40, chunk_overlap=10
    )
    stride: int = (40 - 10) * len(word)
    assert [d.char_start for d in drafts[:-1]] == [k * stride for k in range(len(drafts) - 1)]
    assert_tiles_document(drafts, text)


def test_periodic_pages_all_appear_in_spans() -> None:
    source: list[ExtractedPage] = pages("0 " * 600, "0 " * 600, "0 " * 600)
    drafts: list[ChunkDraft] = chunk_pages(
        source, WhitespaceTokenCounter(), chunk_tokens=40, chunk_overlap=10
    )
    assert_tiles_document(drafts, joined_text(source))
    assert {d.span.start for d in drafts} == {1, 2, 3}
    assert drafts[-1].span.end == 3
    assert drafts[0].span.start == 1


@pytest.mark.parametrize(
    ("text", "chunk_tokens", "chunk_overlap"),
    [
        ("Alpha one. Alpha two! Beta? Gamma… Delta\nline two\n\nPara two. " * 12, 12, 4),
        (" ".join(f"w{i}." for i in range(300)), 20, 5),
        ("  leading\n\n\n\ntrailing  \n", 1, 0),
        ("a\n\nb\n\n" * 30, 3, 1),
    ],
)
def test_chunk_texts_match_the_langchain_splitter(
    text: str, chunk_tokens: int, chunk_overlap: int
) -> None:
    counter: WhitespaceTokenCounter = WhitespaceTokenCounter()
    reference: list[str] = RecursiveCharacterTextSplitter(
        chunk_size=chunk_tokens,
        chunk_overlap=chunk_overlap,
        length_function=counter.count,
        separators=["\n\n", "\n", ". ", "! ", "? ", "… ", " "],
        keep_separator="end",
    ).split_text(text)
    drafts: list[ChunkDraft] = chunk_pages(
        pages(text), counter, chunk_tokens=chunk_tokens, chunk_overlap=chunk_overlap
    )
    assert [d.text for d in drafts] == [chunk.strip() for chunk in reference if chunk.strip()]
    assert_tiles_document(drafts, text)


def test_chunks_that_overcount_when_joined_are_recut_within_the_limit() -> None:
    text: str = " ".join(f"w{i}" for i in range(60))
    counter: OvercountingTokenCounter = OvercountingTokenCounter()
    drafts: list[ChunkDraft] = chunk_pages(pages(text), counter, chunk_tokens=5, chunk_overlap=0)
    assert len(drafts) >= 12
    assert all(d.token_count == counter.count(d.text) <= 5 for d in drafts)
    assert {word for d in drafts for word in d.text.split()} == set(text.split())
    for draft in drafts:
        assert text[draft.char_start : draft.char_end] == draft.text


def test_repeated_text_keeps_the_page_of_each_occurrence() -> None:
    drafts: list[ChunkDraft] = chunk_pages(
        pages("same words here", "same words here", "same words here"),
        WhitespaceTokenCounter(),
        chunk_tokens=3,
        chunk_overlap=0,
    )
    assert [d.span for d in drafts] == [PageSpan(page, page) for page in (1, 2, 3)]


def test_consecutive_chunks_overlap_by_at_most_the_overlap_budget() -> None:
    text: str = " ".join(f"w{i}." for i in range(100))
    drafts: list[ChunkDraft] = chunk_pages(
        pages(text), WhitespaceTokenCounter(), chunk_tokens=20, chunk_overlap=5
    )
    for previous, current in pairwise(drafts):
        overlap: str = text[current.char_start : previous.char_end]
        assert len(overlap.split()) <= 5
        assert current.char_start < previous.char_end


def test_word_longer_than_the_limit_is_split_by_characters_without_loss() -> None:
    word: str = "x" * 35
    drafts: list[ChunkDraft] = chunk_pages(
        pages(f"ab {word} cd"), CharacterTokenCounter(), chunk_tokens=10, chunk_overlap=0
    )
    assert all(d.token_count <= 10 for d in drafts)
    assert "".join(d.text for d in drafts if set(d.text) == {"x"}) == word
    assert "ab" in drafts[0].text
    assert drafts[-1].text.endswith("cd")


def test_whitespace_around_chunks_is_trimmed_and_offsets_follow() -> None:
    source: list[ExtractedPage] = pages("  padded start", "end padded  ")
    joined: str = joined_text(source)
    drafts: list[ChunkDraft] = chunk_pages(
        source, WhitespaceTokenCounter(), chunk_tokens=1, chunk_overlap=0
    )
    assert [d.text for d in drafts] == ["padded", "start", "end", "padded"]
    assert all(joined[d.char_start : d.char_end] == d.text for d in drafts)


def test_no_text_layer_pages_produce_no_chunks() -> None:
    counter: WhitespaceTokenCounter = WhitespaceTokenCounter()
    assert chunk_pages(pages("", "  "), counter, chunk_tokens=10, chunk_overlap=0) == []
    assert chunk_pages([], counter, chunk_tokens=10, chunk_overlap=0) == []


def test_overlap_larger_than_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_pages(pages("text"), WhitespaceTokenCounter(), chunk_tokens=5, chunk_overlap=6)
