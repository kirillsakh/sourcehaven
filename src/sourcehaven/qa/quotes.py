import re
from dataclasses import dataclass

from sourcehaven.qa.citations import CITATION_LABEL

# A sentence ends at a line break, or at `.`, `!`, `?` or `…` (with any closing quotes or
# brackets) followed by whitespace. Abbreviations such as "e.g." are not recognised.
_SENTENCE_END: re.Pattern[str] = re.compile(r"[.!?…][\"'\u201d\u2019)\]]*(?=\s)|\n")
_WORD: re.Pattern[str] = re.compile(r"\w")
_LABELS_ONLY: re.Pattern[str] = re.compile(r"(?:\[S[0-9]+\][\s.,;:!?]*)+")
_MARKDOWN_PREFIX: re.Pattern[str] = re.compile(r"^(?:#{1,6}|[-*+>]|[0-9]+[.)])\s+")
_MARKDOWN_MARKS: re.Pattern[str] = re.compile(r"\*\*|__|`|(?<!\w)[*_]|[*_](?!\w)")
_SPACE_BEFORE_PUNCTUATION: re.Pattern[str] = re.compile(r"\s+([.,;:!?])")
_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")


@dataclass(frozen=True)
class Sentence:
    """A sentence of a text, with `text == source[start:end]`."""

    start: int
    end: int
    text: str


def split_sentences(text: str) -> list[Sentence]:
    """Split text into sentences at line breaks and sentence-ending punctuation.

    Each sentence is stripped of surrounding whitespace, and pieces without a word character
    (blank lines, bullets on their own) are dropped.

    Returns:
        The sentences in text order, each an exact slice of `text`.
    """
    sentences: list[Sentence] = []
    start: int = 0
    for match in _SENTENCE_END.finditer(text):
        _append_sentence(text, start, match.end(), sentences)
        start = match.end()
    _append_sentence(text, start, len(text), sentences)
    return sentences


def _append_sentence(text: str, start: int, end: int, sentences: list[Sentence]) -> None:
    piece: str = text[start:end]
    stripped: str = piece.strip()
    if _WORD.search(stripped) is None:
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
