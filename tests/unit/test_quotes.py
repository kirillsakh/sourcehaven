from uuid import uuid4

import pytest

from sourcehaven.domain.models import Citation, Evidence, PageSpan
from sourcehaven.embeddings.hashing import HashEmbedder
from sourcehaven.embeddings.protocol import Embedder, EmbedderUnavailable
from sourcehaven.generation.prompts import LabelledEvidence
from sourcehaven.qa.citations import quote_snapshot
from sourcehaven.qa.quotes import (
    QUOTE_SELECTION_TIMEOUT_SECONDS,
    PassageSentences,
    Sentence,
    assemble_quote,
    citing_sentences,
    embed_passage_sentences,
    select_quotes,
    split_passage_sentences,
    split_sentences,
)
from tests.support.embeddings import CountingEmbedder, QueryFailingEmbedder, SlowEmbedder

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


CV_TEXT: str = (
    "Alex Novák\n"
    "Summary\n"
    "Backend engineer with 8 years of Python, focused on search, data pipelines and APIs."
    " Recently\n"
    "built retrieval features on PostgreSQL and pgvector for internal documents.\n"
    "\x7f\n"
    "Moved vector search from Elasticsearch to PostgreSQL with pgvector, cutting p95 latency by\n"
    "40%.\n"
    "Must-haves\n"
    "1\n"
    "5+ years of professional Python development."
)


def test_passage_sentences_join_wrapped_lines_and_drop_pieces_without_letters() -> None:
    sentences: list[Sentence] = split_passage_sentences(CV_TEXT)
    assert [s.text.replace("\n", " ") for s in sentences] == [
        "Alex Novák",
        "Summary",
        "Backend engineer with 8 years of Python, focused on search, data pipelines and APIs.",
        "Recently built retrieval features on PostgreSQL and pgvector for internal documents.",
        "Moved vector search from Elasticsearch to PostgreSQL with pgvector, cutting p95 latency"
        " by 40%.",
        "Must-haves",
        "5+ years of professional Python development.",
    ]
    assert all(CV_TEXT[s.start : s.end] == s.text for s in sentences)


def test_answer_sentences_keep_every_line_break_as_a_boundary() -> None:
    assert [s.text for s in split_sentences("Alex has the skills\nlisted in the ad")] == [
        "Alex has the skills",
        "listed in the ad",
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


def _labelled(sources: list[Citation]) -> list[LabelledEvidence]:
    return [LabelledEvidence(label=c.label, evidence=c.evidence) for c in sources]


async def _select(
    answer: str,
    sources: list[Citation],
    *,
    question_vector: list[float],
    embedder: Embedder,
    timeout_seconds: float = QUOTE_SELECTION_TIMEOUT_SECONDS,
) -> list[Citation]:
    return await select_quotes(
        answer,
        sources,
        passage_sentences=embed_passage_sentences(_labelled(sources), embedder),
        question_vector=question_vector,
        embedder=embedder,
        timeout_seconds=timeout_seconds,
    )


async def test_cited_source_quotes_the_sentences_its_citing_sentences_match() -> None:
    passage: str = "Alex Novák, Prague. Led the migration to FastAPI. Enjoys hiking."
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await _select(
        "Alex migrated a service to FastAPI [S1].",
        [_citation("S1", passage, cited=True)],
        question_vector=await embedder.embed_query("hobbies"),
        embedder=embedder,
    )
    assert chosen[0].quote == "…Led the migration to FastAPI. …"


async def test_uncited_and_label_only_sources_use_the_question() -> None:
    passage: str = "The warranty period is 24 months. Support answers within 3 business days."
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await _select(
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
    chosen: list[Citation] = await _select(
        "Dots [S1].",
        [source],
        question_vector=await embedder.embed_query("dots"),
        embedder=embedder,
    )
    assert chosen == [source]


async def test_embedder_errors_propagate() -> None:
    with pytest.raises(EmbedderUnavailable):
        await _select(
            "Fact [S1].",
            [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0],
            embedder=QueryFailingEmbedder(),
        )


async def test_slow_embedder_times_out() -> None:
    with pytest.raises(TimeoutError):
        await _select(
            "Fact [S1].",
            [_citation("S1", "Fact.", cited=True)],
            question_vector=[1.0],
            embedder=SlowEmbedder(delay_seconds=1.0),
            timeout_seconds=0.05,
        )


async def test_quotes_contain_whole_sentences_of_wrapped_passage_lines() -> None:
    embedder: HashEmbedder = HashEmbedder()
    chosen: list[Citation] = await _select(
        "Alex moved vector search to pgvector, cutting p95 latency by 40% [S1].",
        [_citation("S1", CV_TEXT, cited=True)],
        question_vector=await embedder.embed_query("latency"),
        embedder=embedder,
    )
    assert "cutting p95 latency by\n40%." in chosen[0].quote


async def test_selection_after_passages_are_embedded_only_embeds_citing_sentences() -> None:
    embedder: CountingEmbedder = CountingEmbedder()
    sources: list[Citation] = [_citation("S1", "Fact one. Fact two.", cited=True)]
    embedded: dict[str, PassageSentences] = await embed_passage_sentences(
        _labelled(sources), embedder
    )
    embedder.reset()

    async def ready() -> dict[str, PassageSentences]:
        return embedded

    chosen: list[Citation] = await select_quotes(
        "Fact two [S1].",
        sources,
        passage_sentences=ready(),
        question_vector=await embedder.embed_query("fact"),
        embedder=embedder,
    )
    assert chosen[0].quote == "…Fact two."
    assert embedder.document_batches == 0 and embedder.query_batches == 1


def test_neighbouring_sentences_keep_only_the_whitespace_between_them() -> None:
    passage: str = "AI: OpenAI API, LangChain\n\x7f\nLanguages: Czech, English."
    sentences: list[Sentence] = split_passage_sentences(passage)
    assert assemble_quote(passage, sentences, [0, 1]) == (
        "AI: OpenAI API, LangChain\n\nLanguages: Czech, English."
    )


def test_a_short_heading_after_a_long_line_starts_a_new_sentence() -> None:
    passage: str = (
        "Senior Python Developer · Prague, Czech Republic · alex.novak@example.com\n"
        "Summary\n"
        "Backend engineer with 8 years of Python, focused on search and data pipelines,\n"
        "and APIs."
    )
    assert [s.text.replace("\n", " ") for s in split_passage_sentences(passage)] == [
        "Senior Python Developer · Prague, Czech Republic · alex.novak@example.com",
        "Summary",
        "Backend engineer with 8 years of Python, focused on search and data pipelines, and APIs.",
    ]


def test_skipped_dates_between_neighbouring_sentences_are_marked_with_an_ellipsis() -> None:
    passage: str = "Senior Engineer\n2019 - 2023\nLed the migration."
    sentences: list[Sentence] = split_passage_sentences(passage)
    assert assemble_quote(passage, sentences, [0, 1]) == "Senior Engineer … Led the migration."
    amount: str = "Cut latency by\n40%\nwith pgvector."
    amount_sentences: list[Sentence] = split_sentences(amount)
    assert assemble_quote(amount, amount_sentences, [0, 1]) == "Cut latency by … with pgvector."


JOB_AD: str = (
    "About us\nWe are a team of 12.\nMust-haves\n5+ years of Python.\nFastAPI or Django.\n"
    "Nice-to-haves\nTerraform."
)


def test_a_chosen_heading_continues_with_the_sentences_under_it() -> None:
    sentences: list[Sentence] = split_passage_sentences(JOB_AD)
    assert assemble_quote(JOB_AD, sentences, [2]) == (
        "…Must-haves\n5+ years of Python.\nFastAPI or Django. …"
    )


def test_a_heading_continues_only_while_the_quote_fits() -> None:
    sentences: list[Sentence] = split_passage_sentences(JOB_AD)
    assert assemble_quote(JOB_AD, sentences, [2], limit=36) == "…Must-haves\n5+ years of Python. …"


def test_lines_with_commas_or_colons_are_not_headings() -> None:
    passage: str = "Languages: Czech, English\nAI: OpenAI API\nEducation and certification"
    sentences: list[Sentence] = split_passage_sentences(passage)
    assert assemble_quote(passage, sentences, [0]) == "Languages: Czech, English …"


def test_list_numbers_between_neighbouring_sentences_are_dropped_like_bullets() -> None:
    passage: str = "Must-haves\n1\n5+ years of Python.\n2.\nFastAPI or Django."
    sentences: list[Sentence] = split_passage_sentences(passage)
    assert assemble_quote(passage, sentences, [0]) == (
        "Must-haves\n\n5+ years of Python.\n\nFastAPI or Django."
    )
