import asyncio
import math
import re
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, replace

from sourcehaven.domain.models import Citation
from sourcehaven.embeddings.protocol import Embedder
from sourcehaven.generation.prompts import LabelledEvidence
from sourcehaven.qa.citations import CITATION_LABEL, QUOTE_SNAPSHOT_CHARACTERS

QUOTE_SELECTION_TIMEOUT_SECONDS: float = 2.0

# A sentence ends at a line break, or at `.`, `!`, `?` or `…` (with any closing quotes or
# brackets) followed by whitespace. Abbreviations such as "e.g." are not recognised.
_SENTENCE_END: re.Pattern[str] = re.compile(r"[.!?…][\"'\u201d\u2019)\]]*(?=\s)|\n")
_LETTER: re.Pattern[str] = re.compile(r"[^\W\d_]")
_ENDS_SENTENCE: re.Pattern[str] = re.compile(r"[.!?…][\"'\u201d\u2019)\]]*$")
# PDF text breaks at every printed line. A line at least this share of the passage's longest
# line is taken to be wrapped, so it continues onto the next line unless it ends a sentence.
_WRAPPED_LINE_SHARE: float = 0.7
_LABELS_ONLY: re.Pattern[str] = re.compile(r"(?:\[S[0-9]+\][\s.,;:!?]*)+")
_MARKDOWN_PREFIX: re.Pattern[str] = re.compile(r"^(?:#{1,6}|[-*+>]|[0-9]+[.)])\s+")
_MARKDOWN_MARKS: re.Pattern[str] = re.compile(r"\*\*|__|`|(?<!\w)[*_]|[*_](?!\w)")
_SPACE_BEFORE_PUNCTUATION: re.Pattern[str] = re.compile(r"\s+([.,;:!?])")
_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")
_ELLIPSIS: str = "…"
_GAP: str = " … "


@dataclass(frozen=True)
class Sentence:
    """A sentence of a text, with `text == source[start:end]`."""

    start: int
    end: int
    text: str


def split_sentences(text: str) -> list[Sentence]:
    """Split text into sentences at line breaks and sentence-ending punctuation.

    Each sentence is stripped of surrounding whitespace, and pieces without a letter (blank
    lines, bullets or list numbers on their own) are dropped.

    Returns:
        The sentences in text order, each an exact slice of `text`.
    """
    return _split(text, join_wrapped_lines=False)


def split_passage_sentences(text: str) -> list[Sentence]:
    """Split extracted document text into sentences, rejoining lines the layout wrapped.

    Like `split_sentences`, except that a line break inside a sentence is not a boundary: the
    line continues when it does not end with sentence punctuation and the next line starts with
    a lowercase letter, or starts with a letter or digit after a line at least 70% as long as
    the text's longest line. A sentence keeps its line breaks, so it is still an exact slice.

    Returns:
        The sentences in text order, each an exact slice of `text`.
    """
    return _split(text, join_wrapped_lines=True)


def _split(text: str, *, join_wrapped_lines: bool) -> list[Sentence]:
    longest: int = max(len(line) for line in text.split("\n"))
    sentences: list[Sentence] = []
    start: int = 0
    for match in _SENTENCE_END.finditer(text):
        if (
            join_wrapped_lines
            and match.group() == "\n"
            and _continues(text, match.start(), longest)
        ):
            continue
        _append_sentence(text, start, match.end(), sentences)
        start = match.end()
    _append_sentence(text, start, len(text), sentences)
    return sentences


def _continues(text: str, line_break: int, longest: int) -> bool:
    line: str = text[text.rfind("\n", 0, line_break) + 1 : line_break].rstrip()
    following: str = text[line_break + 1 : line_break + 2]
    if not line or not following or _ENDS_SENTENCE.search(line):
        return False
    return following.islower() or (
        following.isalnum() and len(line) >= _WRAPPED_LINE_SHARE * longest
    )


def _append_sentence(text: str, start: int, end: int, sentences: list[Sentence]) -> None:
    piece: str = text[start:end]
    stripped: str = piece.strip()
    if _LETTER.search(stripped) is None:
        return
    offset: int = start + len(piece) - len(piece.lstrip())
    sentences.append(Sentence(start=offset, end=offset + len(stripped), text=stripped))


def citing_sentences(answer: str) -> dict[str, list[str]]:
    """Find, for each cited label, the answer sentences that cite it.

    A sentence made only of labels (written after the full stop, or on its own line) belongs to
    the sentence before it. Sentences are returned as plain words: labels, Markdown markers,
    emphasis and code backticks are removed and whitespace is normalised.

    Returns:
        Each label (such as `"S1"`) in order of first appearance, mapped to its distinct citing
        sentences in answer order; empty when the label cites no words.
    """
    groups: list[tuple[str, list[str]]] = []
    for sentence in split_sentences(answer):
        labels: list[str] = [f"S{digits}" for digits in CITATION_LABEL.findall(sentence.text)]
        if groups and _LABELS_ONLY.fullmatch(sentence.text):
            groups[-1][1].extend(labels)
        else:
            groups.append((sentence.text, labels))
    citing: dict[str, list[str]] = {}
    for text, labels in groups:
        cleaned: str = _plain_words(text)
        for label in labels:
            sentences: list[str] = citing.setdefault(label, [])
            if cleaned and cleaned not in sentences:
                sentences.append(cleaned)
    return citing


def _plain_words(sentence: str) -> str:
    text: str = CITATION_LABEL.sub("", sentence)
    text = _MARKDOWN_PREFIX.sub("", text.strip())
    text = _MARKDOWN_MARKS.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    return text.strip()


def assemble_quote(
    passage: str,
    sentences: Sequence[Sentence],
    ranked: Sequence[int],
    *,
    limit: int = QUOTE_SNAPSHOT_CHARACTERS,
) -> str:
    """Build a quote from a passage's best sentences.

    Sentences are taken in rank order while the quote still fits, stopping at the first that
    does not, and are shown in passage order. Neighbouring sentences keep the passage text
    between them; skipped text is marked with an ellipsis, including before the first and after
    the last kept sentence when the passage goes on. If the best sentence alone does not fit, it
    is cut at a word boundary and ends with an ellipsis.

    Args:
        passage: The text the sentences were split from.
        sentences: `split_sentences(passage)`.
        ranked: Distinct indices into `sentences`, best first; not empty.
        limit: Maximum quote length in characters.

    Returns:
        The quote, verbatim passage text apart from the ellipses.
    """
    kept: list[int] = []
    for index in ranked:
        candidate: list[int] = sorted([*kept, index])
        if len(_render(passage, sentences, candidate)) > limit:
            break
        kept = candidate
    if kept:
        return _render(passage, sentences, kept)
    return _cut(sentences, ranked[0], limit)


def _render(passage: str, sentences: Sequence[Sentence], kept: Sequence[int]) -> str:
    parts: list[str] = [] if kept[0] == 0 else [_ELLIPSIS]
    previous: int | None = None
    for index in kept:
        if previous is not None:
            adjacent: bool = index == previous + 1
            parts.append(
                passage[sentences[previous].end : sentences[index].start] if adjacent else _GAP
            )
        parts.append(sentences[index].text)
        previous = index
    if kept[-1] != len(sentences) - 1:
        parts.append(" " + _ELLIPSIS)
    return "".join(parts)


def _cut(sentences: Sequence[Sentence], index: int, limit: int) -> str:
    prefix: str = "" if index == 0 else _ELLIPSIS
    room: int = limit - len(prefix) - len(_ELLIPSIS)
    text: str = sentences[index].text
    if len(text) <= room:
        return prefix + text + _ELLIPSIS
    cut: str = text[:room]
    if not text[room].isspace():
        boundary: int = cut.rfind(" ")
        if boundary > 0:
            cut = cut[:boundary]
    return prefix + cut.rstrip() + _ELLIPSIS


@dataclass(frozen=True)
class PassageSentences:
    """A passage's sentences and their document embeddings, in passage order."""

    sentences: list[Sentence]
    vectors: list[list[float]]


async def embed_passage_sentences(
    passages: Sequence[LabelledEvidence], embedder: Embedder
) -> dict[str, PassageSentences]:
    """Split the passages given to the model into sentences and embed them as documents.

    The passages are known before generation starts, so this can run while the answer streams.

    Returns:
        Each passage's sentences and vectors, keyed by its label.

    Raises:
        Exception: Whatever the embedder raises.
    """
    split: list[list[Sentence]] = [split_passage_sentences(p.evidence.text) for p in passages]
    texts: list[str] = [sentence.text for sentences in split for sentence in sentences]
    vectors: list[list[float]] = await embedder.embed_documents(texts) if texts else []
    embedded: dict[str, PassageSentences] = {}
    position: int = 0
    for passage, sentences in zip(passages, split, strict=True):
        embedded[passage.label] = PassageSentences(
            sentences=sentences, vectors=vectors[position : position + len(sentences)]
        )
        position += len(sentences)
    return embedded


async def select_quotes(
    answer: str,
    sources: Sequence[Citation],
    *,
    passage_sentences: Awaitable[Mapping[str, PassageSentences]],
    question_vector: Sequence[float],
    embedder: Embedder,
    timeout_seconds: float = QUOTE_SELECTION_TIMEOUT_SECONDS,
) -> list[Citation]:
    """Quote, for each source, the passage sentences that best support the answer.

    A cited source quotes, for each answer sentence citing it, the passage sentence most similar
    to that sentence, best matches first while they fit. An uncited source, or one cited only by
    bare labels, quotes the single sentence most similar to the question. Similarity is the
    cosine of the embedder's vectors: passage sentences as documents, answer sentences as
    queries.

    Args:
        answer: The complete answer text.
        sources: The validated sources, each with its current quote.
        passage_sentences: `embed_passage_sentences` for the supplied passages, usually started
            when generation started; waiting for it counts towards the time limit.
        question_vector: The question's query embedding, made by `embedder`.
        embedder: The active embedder.
        timeout_seconds: Limit for the whole selection, including the wait for
            `passage_sentences`.

    Returns:
        `sources` in order with new quotes; a source whose passage has no sentences keeps its
        quote.

    Raises:
        TimeoutError: If selection takes longer than `timeout_seconds`.
        Exception: Whatever the embedder raises. The caller keeps the existing quotes.
    """
    async with asyncio.timeout(timeout_seconds):
        return await _select_quotes(
            answer, sources, await passage_sentences, question_vector, embedder
        )


async def _select_quotes(
    answer: str,
    sources: Sequence[Citation],
    passages: Mapping[str, PassageSentences],
    question_vector: Sequence[float],
    embedder: Embedder,
) -> list[Citation]:
    citing: dict[str, list[str]] = citing_sentences(answer)
    queries: list[str] = list(
        dict.fromkeys(
            sentence
            for source in sources
            if source.cited
            for sentence in citing.get(source.label, [])
        )
    )
    query_vectors: dict[str, list[float]] = (
        dict(zip(queries, await embedder.embed_queries(queries), strict=True)) if queries else {}
    )
    chosen: list[Citation] = []
    for source in sources:
        passage: PassageSentences | None = passages.get(source.label)
        if passage is None or not passage.sentences:
            chosen.append(source)
            continue
        targets: list[Sequence[float]] = (
            [query_vectors[sentence] for sentence in citing.get(source.label, [])]
            if source.cited
            else []
        )
        ranked: list[int] = _rank(passage.vectors, targets or [question_vector])
        quote: str = assemble_quote(source.evidence.text, passage.sentences, ranked)
        chosen.append(replace(source, quote=quote))
    return chosen


def _rank(
    sentence_vectors: Sequence[Sequence[float]], targets: Sequence[Sequence[float]]
) -> list[int]:
    """Each target's most similar sentence (the earlier on ties), best similarity first."""
    best: dict[int, float] = {}
    for target in targets:
        scores: list[float] = [_cosine(vector, target) for vector in sentence_vectors]
        index: int = max(range(len(scores)), key=scores.__getitem__)
        best[index] = max(best.get(index, -math.inf), scores[index])
    return sorted(best, key=lambda index: (-best[index], index))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    norms: float = math.sqrt(math.fsum(a * a for a in left)) * math.sqrt(
        math.fsum(b * b for b in right)
    )
    if norms == 0.0:
        return 0.0
    return math.fsum(a * b for a, b in zip(left, right, strict=True)) / norms
