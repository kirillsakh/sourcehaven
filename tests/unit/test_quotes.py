from uuid import uuid4

import pytest

from sourcehaven.domain.models import Citation, Evidence, PageSpan
from sourcehaven.embeddings.hashing import HashEmbedder
from sourcehaven.embeddings.protocol import EmbedderUnavailable
from sourcehaven.qa.citations import quote_snapshot
from sourcehaven.qa.quotes import (
    Sentence,
    assemble_quote,
    citing_sentences,
    select_quotes,
    split_sentences,
)
from tests.support.embeddings import QueryFailingEmbedder, SlowEmbedder

PASSAGE: str = (
    "Alex Novák. Prague.\nLed the migration to FastAPI. Cut p95 by 40%.\nMentored four engineers."
)


def test_sentences_slice_the_passage_exactly() -> None:
    text: str = 'Senior Engineer.\n• Led the migration! Wait… then "yes." Then (done.) end'
    sentences: list[Sentence] = split_sentences(text)
    assert [s.text for s in sentences] == [
        "Senior Engineer.",
        "• Led the migration!",
        "Wait…",
        'then "yes."',
        "Then (done.)",
        "end",
    ]
    assert all(text[s.start : s.end] == s.text for s in sentences)


def test_lines_without_full_stops_are_sentences_and_blank_pieces_are_dropped() -> None:
    assert [s.text for s in split_sentences("Skills\n\n  •  \nPython, FastAPI\n")] == [
        "Skills",
        "Python, FastAPI",
    ]


def test_label_after_the_full_stop_or_on_its_own_line_cites_the_preceding_sentence() -> None:
    answer: str = "Support answers in 3 days. [S1]\nThe warranty is 24 months.\n[S2]"
    assert citing_sentences(answer) == {
        "S1": ["Support answers in 3 days."],
        "S2": ["The warranty is 24 months."],
    }


def test_markdown_and_labels_are_removed_and_shared_sentences_count_for_each_label() -> None:
    answer: str = "## Fit\n- **Python:** 7 years of `FastAPI` work [S2][S3].\n- Mentoring [S2]."
    assert citing_sentences(answer) == {
        "S2": ["Python: 7 years of FastAPI work.", "Mentoring."],
        "S3": ["Python: 7 years of FastAPI work."],
    }


def test_label_without_words_has_no_citing_sentence() -> None:
    assert citing_sentences("Intro.\n[S1][S2]") == {"S1": ["Intro."], "S2": ["Intro."]}
    assert citing_sentences("[S1]") == {"S1": []}


def test_quote_keeps_picks_in_passage_order_with_ellipses() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [4, 2]) == (
        "…Led the migration to FastAPI. … Mentored four engineers."
    )


def test_adjacent_picks_keep_the_source_text_between_them() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [3, 2]) == (
        "…Led the migration to FastAPI. Cut p95 by 40%. …"
    )


def test_picks_stop_at_the_first_that_does_not_fit() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    assert assemble_quote(PASSAGE, sentences, [2, 4, 0], limit=60) == (
        "…Led the migration to FastAPI. … Mentored four engineers."
    )


def test_overlong_sentence_is_cut_at_a_word_boundary() -> None:
    run: str = " ".join(["Python"] * 80)
    quote: str = assemble_quote(run, split_sentences(run), [0])
    assert len(quote) <= 300 and quote.endswith("Python…") and run.startswith(quote[:-1])


def test_quotes_are_verbatim_apart_from_ellipses() -> None:
    sentences: list[Sentence] = split_sentences(PASSAGE)
    for ranked in ([0], [1, 3], [4, 0, 2]):
        quote: str = assemble_quote(PASSAGE, sentences, ranked)
        assert all(part.strip() in PASSAGE for part in quote.split("…") if part.strip())


def test_sentence_that_only_overflows_with_the_trailing_ellipsis_keeps_every_word() -> None:
    first: str = "word " * 59 + "end."
    passage: str = first + " Next sentence."
    quote: str = assemble_quote(passage, split_sentences(passage), [0])
    assert quote == first + "…" and len(quote) <= 300


def _citation(label: str, text: str, *, cited: bool) -> Citation:
    evidence: Evidence = Evidence(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_name="doc.pdf",
        text=text,
        span=PageSpan(start=1, end=1),
        similarity=0.5,
    )
    return Citation(label=label, evidence=evidence, cited=cited, quote=quote_snapshot(text))


async def test_cited_source_quotes_the_sentences_its_citing_sentences_match() -> None:
    passage: str = "Alex Novák, Prague. Led the migration to FastAPI. Enjoys hiking."
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await select_quotes(
        "Alex migrated a service to FastAPI [S1].",
        [_citation("S1", passage, cited=True)],
        question_vector=await embedder.embed_query("hobbies"),
        embedder=embedder,
    )
    assert chosen[0].quote == "…Led the migration to FastAPI. …"


async def test_uncited_and_label_only_sources_use_the_question() -> None:
    passage: str = "The warranty period is 24 months. Support answers within 3 business days."
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await select_quotes(
        "[S1]",
        [_citation("S1", passage, cited=True), _citation("S2", passage, cited=False)],
        question_vector=await embedder.embed_query(
            "Within how many business days does support answer?"
        ),
        embedder=embedder,
    )
    assert [c.quote for c in chosen] == ["…Support answers within 3 business days."] * 2


async def test_source_without_sentences_keeps_its_quote() -> None:
    embedder: HashEmbedder = HashEmbedder()
    source: Citation = _citation("S1", "• • •", cited=True)
    chosen: list[Citation] = await select_quotes(
        "Dots [S1].",
        [source],
        question_vector=await embedder.embed_query("dots"),
        embedder=embedder,
    )
    assert chosen == [source]


async def test_embedder_errors_propagate() -> None:
    with pytest.raises(EmbedderUnavailable):
        await select_quotes(
            "Fact [S1].",
            [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0],
            embedder=QueryFailingEmbedder(),
        )


async def test_slow_embedder_times_out() -> None:
    with pytest.raises(TimeoutError):
        await select_quotes(
            "Fact [S1].",
            [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0],
            embedder=SlowEmbedder(delay_seconds=1.0),
            timeout_seconds=0.05,
        )
